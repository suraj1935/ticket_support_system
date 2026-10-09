"""Strict allow-list validation for LLM-produced query plans.

A plan is data, never SQL: every key, column, operator and aggregation must be
on an allow-list, and values must be plain scalars. Anything else is rejected
before the compiler sees it.
"""
import re

COLUMNS = (
    "ticket_id", "created_at", "category", "priority", "status",
    "response_time_hrs", "resolution_time_hrs", "agent_id", "customer_rating",
    "issue_summary",
)
OPERATORS = ("==", "=", "!=", ">", "<", ">=", "<=", "LIKE", "IN")
AGG_TYPES = ("count", "avg", "mean", "sum", "min", "max")
PLAN_KEYS = {"select", "aggregation", "filters", "group_by", "order_by", "limit", "error"}
MAX_LIMIT = 1000

_ALIAS_RE = re.compile(r"^(count|avg|mean|sum|min|max)_(\*|[a-z_]+)$")


class PlanValidationError(ValueError):
    pass


def _scalar(v):
    return v is None or (isinstance(v, (str, int, float)) and not isinstance(v, bool))


def _check_column(col, what, allow_star=False):
    if not isinstance(col, str):
        raise PlanValidationError(f"{what} must be a column name string")
    if col == "*" and allow_star:
        return
    if col not in COLUMNS:
        raise PlanValidationError(f"Unknown column in {what}: {col!r}")


def validate_plan(plan):
    """Return the plan unchanged if it is valid, else raise PlanValidationError."""
    if not isinstance(plan, dict):
        raise PlanValidationError("Plan must be a JSON object")
    extra = set(plan) - PLAN_KEYS
    if extra:
        raise PlanValidationError(f"Unsupported plan keys (raw SQL is not allowed): {sorted(extra)}")
    if "error" in plan:
        return plan

    select = plan.get("select", ["*"])
    if not isinstance(select, list) or not select:
        raise PlanValidationError("select must be a non-empty list")
    for c in select:
        if isinstance(c, str) and _ALIAS_RE.match(c):
            continue
        _check_column(c, "select", allow_star=True)

    agg = plan.get("aggregation")
    if agg is not None:
        if not isinstance(agg, dict) or set(agg) != {"type", "column"}:
            raise PlanValidationError("aggregation must be {type, column}")
        if not isinstance(agg["type"], str) or agg["type"].lower() not in AGG_TYPES:
            raise PlanValidationError(f"Unknown aggregation type: {agg['type']!r}")
        _check_column(agg["column"], "aggregation", allow_star=agg["type"].lower() == "count")

    filters = plan.get("filters", [])
    if not isinstance(filters, list):
        raise PlanValidationError("filters must be a list")
    for f in filters:
        if not isinstance(f, dict) or not {"column", "op"} <= set(f) <= {"column", "op", "value"}:
            raise PlanValidationError("each filter must be {column, op, value}")
        _check_column(f["column"], "filter")
        op = f["op"].upper() if isinstance(f["op"], str) else f["op"]
        if op not in OPERATORS:
            raise PlanValidationError(f"Unknown operator: {f['op']!r}")
        val = f.get("value")
        if op == "IN":
            if not isinstance(val, list) or not val or not all(_scalar(x) for x in val):
                raise PlanValidationError("IN needs a non-empty list of scalar values")
        elif not _scalar(val):
            raise PlanValidationError("filter value must be a scalar")

    group_by = plan.get("group_by")
    if group_by is not None:
        if isinstance(group_by, list):
            raise PlanValidationError("Multi-column group_by is not supported")
        _check_column(group_by, "group_by")

    order_by = plan.get("order_by")
    if order_by is not None:
        if not isinstance(order_by, dict) or not set(order_by) <= {"column", "direction"}:
            raise PlanValidationError("order_by must be {column, direction}")
        col = order_by.get("column")
        if isinstance(col, str) and _ALIAS_RE.match(col):
            # An alias that names no real output column is silently ignored by SQLite (the
            # quoted name becomes a string literal), which would return an unsorted row as
            # if it were the top one. Accept only the plan's own aggregate alias; repair a
            # sloppy one of the same aggregate type (e.g. "avg_*"), reject the rest.
            if agg is None:
                raise PlanValidationError(f"order_by {col!r} refers to an aggregate but the plan has none")
            atype = "avg" if agg["type"].lower() == "mean" else agg["type"].lower()
            real = f"{atype}_{agg['column']}"
            if col != real:
                if col.split("_", 1)[0] != atype:
                    raise PlanValidationError(f"order_by {col!r} does not match the aggregate {real!r}")
                order_by["column"] = real
        else:
            _check_column(col, "order_by")
        if str(order_by.get("direction", "ASC")).upper() not in ("ASC", "DESC"):
            raise PlanValidationError("order_by direction must be ASC or DESC")

    limit = plan.get("limit")
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise PlanValidationError(f"limit must be an integer 1..{MAX_LIMIT}")
    return plan
