import re

DIMS = {"agent": "agent_id", "category": "category", "priority": "priority", "status": "status"}
_DIM = r"(agent|category|priority|status)"

# Words that signal a filter, breakdown or time window. If one survives after a branch has
# consumed the phrases it understands, the question asks for more than the branch computes,
# so we refuse instead of answering a simpler question than the one that was asked.
_UNMAPPED = re.compile(
    r"\b(billing|technical|general|categor(?:y|ies)|agents?|priorit(?:y|ies)|critical|high|medium|low|"
    r"escalated|open|resolved|unresolved|status|per|each|by|between|before|after|since|during|"
    r"week|month|today|yesterday|over|under|above|below|more than|less than)\b"
)


def _refuse(q, consumed):
    rest = q
    for pat in consumed:
        rest = re.sub(pat, " ", rest)
    m = _UNMAPPED.search(rest)
    if m:
        return {"error": f"The fallback parser cannot map '{m.group(0)}' in this question to a supported query. "
                         "Rephrase it, or start Ollama for broader coverage."}
    return None


def _status_filter(q):
    if re.search(r"\bunresolved\b", q):
        return [{"column": "status", "op": "!=", "value": "Resolved"}], [r"\bunresolved\b"]
    if re.search(r"\bresolved\b", q):
        return [{"column": "status", "op": "==", "value": "Resolved"}], [r"\bresolved\b"]
    return [], []


def fallback_regex_parser(question):
    """Graceful degradation when LLM fails or is not available.

    Answers a small set of phrasings correctly and refuses everything else, including
    questions that look like a supported one but carry an extra filter or breakdown."""
    q = re.sub(r"\s+", " ", question.lower()).strip(" ?.!")
    count = {"type": "count", "column": "*"}

    plan, consumed = None, []

    m = re.search(rf"\b(?:per|by|each) {_DIM}\b", q)
    if "how many" in q and m:
        filters, c = _status_filter(q)
        plan = {"select": [DIMS[m.group(1)]], "aggregation": count, "group_by": DIMS[m.group(1)]}
        if filters:
            plan["filters"] = filters
        consumed = ["how many", re.escape(m.group(0))] + c

    elif "how many critical tickets are unresolved" in q:
        plan = {"filters": [{"column": "priority", "op": "==", "value": "Critical"},
                            {"column": "status", "op": "!=", "value": "Resolved"}], "aggregation": count}
        consumed = ["how many", r"\bcritical\b", r"\bunresolved\b"]

    elif "how many" in q and "unresolved" in q:
        plan = {"filters": [{"column": "status", "op": "!=", "value": "Resolved"}], "aggregation": count}
        consumed = ["how many", r"\bunresolved\b"]

    elif "show me" in q and "unresolved" in q:
        plan = {"filters": [{"column": "status", "op": "!=", "value": "Resolved"}], "limit": 50}
        consumed = ["show me", r"\bunresolved\b"]

    elif "how many" in q and re.search(r"\bresolved\b", q):
        plan = {"filters": [{"column": "status", "op": "==", "value": "Resolved"}], "aggregation": count}
        consumed = ["how many", r"\bresolved\b"]

    else:
        m = re.search(rf"\b(?:which|what) {_DIM} (?:has|had) the (lowest|highest|best|worst) average (?:customer )?rating\b", q)
        if m:
            direction = "ASC" if m.group(2) in ("lowest", "worst") else "DESC"
            dim = DIMS[m.group(1)]
            plan = {"select": [dim], "aggregation": {"type": "avg", "column": "customer_rating"}, "group_by": dim,
                    "order_by": {"column": "avg_customer_rating", "direction": direction}, "limit": 1}
            consumed = [re.escape(m.group(0))]
        else:
            m = re.search(rf"\b(?:which|what) {_DIM} (?:has |had )?(resolved )?the most tickets\b", q)
            if m:
                dim = DIMS[m.group(1)]
                plan = {"select": [dim], "aggregation": count, "group_by": dim,
                        "order_by": {"column": "count_*", "direction": "DESC"}, "limit": 1}
                if m.group(2):
                    plan["filters"] = [{"column": "status", "op": "==", "value": "Resolved"}]
                consumed = [re.escape(m.group(0))]
            elif "average rating" in q and "technical" in q:
                plan = {"aggregation": {"type": "avg", "column": "customer_rating"},
                        "filters": [{"column": "category", "op": "==", "value": "Technical"}]}
                consumed = ["average rating", r"\btechnical\b"]

    if plan is None:
        return {"error": "I couldn't understand that question."}
    return _refuse(q, consumed) or plan
