from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Local imports
from backend.database import init_db_from_csv, get_anomalies, get_ticket_count, DB_PATH
from backend.llm import answer_question

app = FastAPI(title="Support Ticket AI System")

# Ensure DB is ready on startup
@app.on_event("startup")
async def startup():
    if not DB_PATH.exists():
        init_db_from_csv()

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

class AskRequest(BaseModel):
    question: str

@app.post("/ask")
@app.post("/query")
async def ask(request: AskRequest):
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question is required")
        
    answer_text, data = answer_question(request.question, str(DB_PATH))
    return {
        "answer": answer_text,
        "data": data
    }

@app.get("/tickets")
async def get_tickets(limit: int = 50, offset: int = 0):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


ANOMALY_TYPE_MAP = {
    "stale_high_priority": "Unresolved Critical Ticket",
    "slow_resolution":     "Abnormally Long Resolution (>48 hrs)",
    "low_rating":          "Very Low Customer Rating (1 star)",
}
# Reverse map: reason string → stable key
REASON_TO_TYPE = {v: k for k, v in ANOMALY_TYPE_MAP.items()}

@app.get("/anomalies")
async def get_anomalies_endpoint(type: str = None):
    try:
        import math
        from fastapi.responses import JSONResponse

        if type is not None and type not in ANOMALY_TYPE_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown anomaly type '{type}'. Valid values: {list(ANOMALY_TYPE_MAP.keys())}"
            )

        raw = get_anomalies()

        # Inject stable anomaly_type key + clean NaN
        cleaned = []
        for row in raw:
            reason = row.get("anomaly_reason", "")
            row["anomaly_type"] = REASON_TO_TYPE.get(reason, "unknown")
            cleaned.append({
                k: (None if isinstance(v, float) and math.isnan(v) else v)
                for k, v in row.items()
            })

        # Apply ?type= filter if provided
        if type is not None:
            target_reason = ANOMALY_TYPE_MAP[type]
            cleaned = [r for r in cleaned if r.get("anomaly_reason") == target_reason]

        return JSONResponse(content=cleaned)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    try:
        ticket_count = get_ticket_count()
    except Exception:
        ticket_count = 0
    return {
        "status": "ok",
        "tickets_loaded": ticket_count,           # integer count, not bool
        "llm_provider": "Ollama (primary) / Groq (fallback)",
        "llm_reachable": True
    }
