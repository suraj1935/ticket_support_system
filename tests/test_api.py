def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["tickets_loaded"] == 2000
    assert {"llm_provider", "llm_reachable"} <= set(body)


def test_query_count_shape_and_value(client):
    r = client.post("/query", json={"question": "How many tickets are unresolved?"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"answer", "data"}
    assert isinstance(body["answer"], str) and isinstance(body["data"], list)
    assert body["answer"] == "47 tickets match this query."


def test_query_unknown_question_is_safe_error(client):
    body = client.post("/query", json={"question": "what is the weather"}).json()
    assert set(body) == {"answer", "data"} and body["data"] == []


def test_query_missing_field_is_422(client):
    assert client.post("/query", json={}).status_code == 422


def test_anomalies_shape(client):
    r = client.get("/anomalies")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 115
    for k in ("ticket_id", "anomaly_reason", "anomaly_type", "priority", "status"):
        assert k in rows[0]
    assert {x["anomaly_type"] for x in rows} == {"stale_high_priority", "slow_resolution", "low_rating"}


def test_anomalies_type_filter_and_bad_type(client):
    rows = client.get("/anomalies", params={"type": "stale_high_priority"}).json()
    assert len(rows) == 19 and all(x["priority"] == "Critical" and x["status"] != "Resolved" for x in rows)
    assert client.get("/anomalies", params={"type": "bogus"}).status_code == 400


def test_tickets_shape_and_paging(client):
    r = client.get("/tickets", params={"limit": 5})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5
    assert set(rows[0]) == {"ticket_id", "created_at", "category", "priority", "status",
                            "response_time_hrs", "resolution_time_hrs", "agent_id",
                            "customer_rating", "issue_summary"}
    page2 = client.get("/tickets", params={"limit": 5, "offset": 5}).json()
    assert page2[0]["ticket_id"] != rows[0]["ticket_id"]
