import sqlite3

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
import backend.database as database
import backend.llm as llm


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A throwaway DB built from the real CSV; the project tickets.db is never touched."""
    path = tmp_path / "tickets.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(app_module, "DB_PATH", path)
    database.init_db_from_csv()
    return path


@pytest.fixture()
def regex_mode(monkeypatch):
    """Force the deterministic regex parser: no Ollama, no Groq."""
    monkeypatch.setattr(llm, "call_ollama", lambda prompt: None)
    monkeypatch.setattr(llm, "call_groq", lambda prompt: None)


@pytest.fixture()
def client(db_path, regex_mode):
    return TestClient(app_module.app)


def db_fingerprint(path):
    con = sqlite3.connect(path)
    try:
        schema = con.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        n = con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        checksum = con.execute(
            "SELECT group_concat(ticket_id || status || priority || ifnull(agent_id,''), '|') "
            "FROM (SELECT * FROM tickets ORDER BY ticket_id)").fetchone()[0]
        return schema, n, checksum
    finally:
        con.close()
