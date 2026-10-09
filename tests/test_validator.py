import copy

import pytest

from backend.validator import PlanValidationError, validate_plan

GOOD = {
    "select": ["agent_id"],
    "aggregation": {"type": "count", "column": "*"},
    "filters": [{"column": "status", "op": "==", "value": "Resolved"}],
    "group_by": "agent_id",
    "order_by": {"column": "count_*", "direction": "DESC"},
    "limit": 1,
}


def with_(**changes):
    p = copy.deepcopy(GOOD)
    p.update(changes)
    return p


def test_valid_plan_passes():
    assert validate_plan(copy.deepcopy(GOOD)) == GOOD


@pytest.mark.parametrize("plan", [
    with_(filters=[{"column": "password", "op": "==", "value": "x"}]),
    with_(select=["agent_id, (SELECT 1)"]),
    with_(group_by="nope"),
    with_(aggregation={"type": "avg", "column": "salary"}),
    with_(order_by={"column": "salary", "direction": "ASC"}),
], ids=["filter-col", "select-col", "group-col", "agg-col", "order-col"])
def test_unknown_columns_rejected(plan):
    with pytest.raises(PlanValidationError, match="Unknown column"):
        validate_plan(plan)


@pytest.mark.parametrize("op", ["~", "<>", "OR 1=1 --", "BETWEEN", "; DROP TABLE tickets", ""])
def test_unknown_operators_rejected(op):
    with pytest.raises(PlanValidationError):
        validate_plan(with_(filters=[{"column": "status", "op": op, "value": "x"}]))


def test_unknown_aggregation_rejected():
    with pytest.raises(PlanValidationError, match="aggregation"):
        validate_plan(with_(aggregation={"type": "median", "column": "customer_rating"}))


@pytest.mark.parametrize("key", ["sql", "raw_sql", "query", "where", "having", "union", "SQL"])
def test_raw_sql_keys_rejected(key):
    with pytest.raises(PlanValidationError, match="raw SQL"):
        validate_plan(with_(**{key: "SELECT * FROM tickets; DROP TABLE tickets"}))


@pytest.mark.parametrize("plan", [
    with_(filters=[{"column": "status", "op": "==", "value": "x", "sql": "1=1"}]),
    with_(filters=[{"column": "status", "op": "IN", "value": [{"$ne": 1}]}]),
    with_(filters=[{"column": "status", "op": "==", "value": {"nested": "obj"}}]),
    with_(group_by=["agent_id", "category"]),
    with_(limit="10; DROP TABLE tickets"),
    with_(limit=-5),
    with_(limit=10**6),
    with_(order_by={"column": "agent_id", "direction": "ASC; DROP TABLE tickets"}),
    "SELECT * FROM tickets",
    ["select", "*"],
], ids=lambda p: str(p)[:40])
def test_other_malformed_plans_rejected(plan):
    with pytest.raises(PlanValidationError):
        validate_plan(plan)


def test_error_plan_is_passed_through():
    assert validate_plan({"error": "nope"}) == {"error": "nope"}


def test_sloppy_order_by_alias_of_same_aggregate_is_repaired():
    # real LLM output seen in eval: "avg_*" instead of "avg_customer_rating"
    plan = {"aggregation": {"type": "avg", "column": "customer_rating"}, "group_by": "agent_id",
            "order_by": {"column": "avg_*", "direction": "ASC"}, "limit": 1}
    assert validate_plan(plan)["order_by"]["column"] == "avg_customer_rating"


@pytest.mark.parametrize("plan", [
    {"aggregation": {"type": "avg", "column": "customer_rating"}, "order_by": {"column": "count_*"}},
    {"aggregation": {"type": "count", "column": "*"}, "order_by": {"column": "avg_customer_rating"}},
    {"group_by": "agent_id", "order_by": {"column": "count_*"}},
])
def test_order_by_alias_that_matches_no_output_column_is_rejected(plan):
    with pytest.raises(PlanValidationError):
        validate_plan(plan)


def test_unsorted_alias_can_no_longer_return_an_arbitrary_top_row(db_path):
    from backend.llm import compile_plan_to_sql
    import sqlite3
    sql, params = compile_plan_to_sql({
        "aggregation": {"type": "avg", "column": "customer_rating"}, "group_by": "agent_id",
        "order_by": {"column": "avg_*", "direction": "ASC"}, "limit": 1})
    row = sqlite3.connect(db_path).execute(sql, params).fetchone()
    assert row[0] == "AGT-08"
