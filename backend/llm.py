import json
import os
import re
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_CLOUD_MODEL = os.getenv("OLLAMA_CLOUD_MODEL", "gpt-oss:120b-cloud")

from backend.prompts import build_system_prompt
from backend.fallback import fallback_regex_parser
from backend.validator import validate_plan
import sqlite3

class QueryParseError(Exception):
    pass

def get_system_prompt():
    """Build system prompt with reference date injected from the database."""
    try:
        con = sqlite3.connect('tickets.db')
        max_date = con.execute("SELECT MAX(created_at) FROM tickets").fetchone()[0]
        con.close()
        reference_date = str(max_date)[:10] if max_date else None
        return build_system_prompt(reference_date)
    except Exception:
        return build_system_prompt()

def call_ollama(prompt):
    sys_prompt = get_system_prompt()
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt}
    ]
    
    try:
        if OLLAMA_API_KEY:
            # Direct cloud inference
            url = "https://ollama.com/api/chat"
            headers = {
                "Authorization": f"Bearer {OLLAMA_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": OLLAMA_CLOUD_MODEL,
                "messages": messages,
                "stream": False,
                "format": "json"
            }
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()['message']['content']
        else:
            # Local fallback
            import ollama
            response = ollama.chat(model=OLLAMA_MODEL, messages=messages, format="json")
            return response['message']['content']
    except Exception as e:
        print(f"Ollama failed: {e}")
        return None

def call_groq(prompt):
    if not GROQ_API_KEY:
        return None
    try:
        sys_prompt = get_system_prompt()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        response = requests.post(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Groq failed: {e}")
        return None

def _validate_intent(question: str, plan: dict) -> None:
    q = question.lower().strip()
    COUNT_TRIGGERS = ("how many", "count of", "number of", "total number")
    
    wants_count = any(t in q for t in COUNT_TRIGGERS)
    
    agg = plan.get("aggregation", {})
    has_count = agg.get("type", "").lower() == "count"

    if wants_count and not has_count:
        raise QueryParseError(
            f"Question asks for a count but plan has no count aggregation. Plan: {json.dumps(plan)}"
        )

def get_query_plan(question: str, retry=False):
    print("Trying Ollama...")
    plan_text = call_ollama(question)
    
    if not plan_text:
        print("Ollama unavailable, trying Groq fallback...")
        plan_text = call_groq(question)
        
    if not plan_text:
        print("LLMs unavailable, using Regex Fallback...")
        plan = fallback_regex_parser(question)
    else:
        try:
            match = re.search(r'\{.*\}', plan_text.replace('\n', ' '))
            if match:
                plan = json.loads(match.group(0))
            else:
                plan = json.loads(plan_text)
        except json.JSONDecodeError:
            print("Failed to parse LLM output as JSON. Using fallback.")
            plan = fallback_regex_parser(question)
            
    try:
        _validate_intent(question, plan)
        return plan
    except QueryParseError as e:
        print(f"Validation failed: {e}")
        if not retry:
            print("Retrying LLM with validation feedback...")
            # Append validation error to the prompt for one retry
            return get_query_plan(f"{question}\n\nPrevious attempt failed: {str(e)}\nPlease fix it and output correct JSON.", retry=True)
        return fallback_regex_parser(question)

def compile_plan_to_sql(plan):
    """Compiles the JSON query plan into parameterized SQL."""
    validate_plan(plan)
    if "error" in plan:
        raise ValueError(plan["error"])
        
    select_cols = plan.get("select", ["*"])
    
    agg = plan.get("aggregation")
    if agg:
        agg_type = agg['type'].upper()
        if agg_type == "MEAN":
            agg_type = "AVG"
        alias = f"{agg_type.lower()}_{agg['column']}"
        select_cols = [c for c in select_cols if c != alias]
        
    group_by = plan.get("group_by")
    if group_by and group_by not in select_cols:
        if select_cols == ["*"]:
            select_cols = [group_by]
        else:
            select_cols.insert(0, group_by)
            
    select_clause = ", ".join(select_cols)
    
    agg = plan.get("aggregation")
    if agg:
        agg_type = agg['type'].upper()
        if agg_type == "MEAN":
            agg_type = "AVG"
        # use double quotes for the alias to allow '*' characters safely in SQLite
        agg_str = f"{agg_type}({agg['column']}) as \"{agg_type.lower()}_{agg['column']}\""
        if select_cols == ["*"]:
            select_clause = agg_str
        else:
            select_clause += f", {agg_str}"
            
    sql = f"SELECT {select_clause} FROM tickets"
    params = []
    
    filters = plan.get("filters", [])
    if filters:
        where_clauses = []
        for f in filters:
            col = f["column"]
            op = f["op"].upper()
            if op == "==":
                op = "="
            val = f.get("value")
            
            # Normalize date boundaries for created_at
            if col == "created_at" and isinstance(val, str) and len(val) == 10:
                if op == "<":
                    val += " 00:00:00"
                elif op == "<=":
                    val += " 23:59:59"
                elif op == ">=":
                    val += " 00:00:00"
                elif op == ">":
                    val += " 23:59:59"
                    
            if re.match(r'^[a-zA-Z0-9_]+$', col):
                if val is None:
                    if op == "=":
                        where_clauses.append(f"{col} IS NULL")
                    elif op == "!=":
                        where_clauses.append(f"{col} IS NOT NULL")
                else:
                    if op in ['=', '!=', '>', '<', '>=', '<=', 'LIKE']:
                        where_clauses.append(f"{col} {op} ?")
                        params.append(val)
                    elif op == 'IN' and isinstance(val, list):
                        placeholders = ", ".join(["?"] * len(val))
                        where_clauses.append(f"{col} IN ({placeholders})")
                        params.extend(val)
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
            
    group_by = plan.get("group_by")
    if group_by and re.match(r'^[a-zA-Z0-9_]+$', group_by):
        sql += f" GROUP BY {group_by}"
        
    order_by = plan.get("order_by")
    if order_by:
        col = order_by.get("column", "")
        if "*" in col and not col.startswith('"'):
            col = f'"{col}"'
        direction = order_by.get("direction", "ASC").upper()
        if re.match(r'^[a-zA-Z0-9_"*]+$', col) and direction in ["ASC", "DESC"]:
            sql += f" ORDER BY {col} {direction}"
            
    limit = plan.get("limit")
    if limit:
        try:
            sql += f" LIMIT {int(limit)}"
        except ValueError:
            pass
            
    return sql, params

def _normalize(question: str) -> str:
    q = question.strip()
    q = re.sub(r"\s+", " ", q)          # collapse internal whitespace
    q = re.sub(r"\s+\?", "?", q)        # remove space before ?
    q = re.sub(r"\s+\.", ".", q)        # remove space before .
    return q

def answer_question(question, db_path):
    question = _normalize(question)
    try:
        plan = get_query_plan(question)
        sql, params = compile_plan_to_sql(plan)
        
        print(f"Executing SQL: {sql} with params: {params}")
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        results = [dict(row) for row in rows]
        
        from backend.formatter import format_answer
        answer_text, display_rows = format_answer(question, plan, results)
        
        return answer_text, display_rows
    except Exception as e:
        print(f"Error answering question: {e}")
        return f"I had trouble answering that: {str(e)}", []
