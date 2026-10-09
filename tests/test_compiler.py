import re

import pytest

from backend.llm import compile_plan_to_sql
from backend.validator import COLUMNS, PlanValidationError

EVIL = "'; DROP TABLE tickets; --"


def test_values_are_bound_not_inlined():
    sql, params = compile_plan_to_sql({
        "filters": [{"column": "status", "op": "==", "value": EVIL},
                    {"column": "agent_id", "op": "IN", "value": [EVIL, "AGT-01"]},
                    {"column": "issue_summary", "op": "LIKE", "value": "%" + EVIL}],
    })
    assert "DROP" not in sql and EVIL not in sql and "AGT-01" not in sql
    assert sql.count("?") == len(params) == 4
    assert params == [EVIL, EVIL, "AGT-01", "%" + EVIL]


def test_sql_string_only_contains_whitelisted_identifiers_and_placeholders():
    sql, _ = compile_plan_to_sql({
        "select": ["agent_id"],
        "aggregation": {"type": "avg", "column": "customer_rating"},
        "filters": [{"column": "category", "op": "==", "value": "Technical"}],
        "group_by": "agent_id",
        "order_by": {"column": "avg_customer_rating", "direction": "ASC"},
        "limit": 1,
    })
    allowed = {w.lower() for w in COLUMNS} | {
        "select", "from", "tickets", "where", "group", "by", "order", "asc", "desc",
        "limit", "avg", "as", "and", "avg_customer_rating", "1"}
    words = set(re.findall(r"[A-Za-z_0-9]+", sql.lower()))
    assert words <= allowed, words - allowed


@pytest.mark.parametrize("plan", [
    {"select": ["agent_id FROM tickets; DROP TABLE tickets; --"]},
    {"aggregation": {"type": "count", "column": "*) FROM tickets; DROP TABLE tickets; --"}},
    {"group_by": "agent_id; DROP TABLE tickets"},
    {"filters": [{"column": "status; DROP TABLE tickets", "op": "==", "value": 1}]},
    {"order_by": {"column": "1; DROP TABLE tickets", "direction": "ASC"}},
    {"sql": "DROP TABLE tickets"},
])
def test_injection_in_identifiers_never_reaches_sql(plan):
    with pytest.raises(PlanValidationError):
        compile_plan_to_sql(plan)


def test_nonnumeric_limit_rejected():
    with pytest.raises(PlanValidationError):
        compile_plan_to_sql({"limit": "5 UNION SELECT 1"})
