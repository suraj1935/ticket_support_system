import pathlib

import pandas as pd
import pytest

from backend.fallback import fallback_regex_parser
from backend.formatter import format_answer
from backend.llm import answer_question

df = pd.read_csv(pathlib.Path(__file__).resolve().parent.parent / "support_tickets.csv")
avg_by_agent = df.groupby("agent_id").customer_rating.mean()


# --- formatter: ranking word follows the sort direction -------------------------------

def avg_plan(direction):
    return {"aggregation": {"type": "avg", "column": "customer_rating"}, "group_by": "agent_id",
            "order_by": {"column": "avg_customer_rating", "direction": direction}, "limit": 1}


@pytest.mark.parametrize("direction,word", [("ASC", "lowest"), ("DESC", "highest")])
def test_avg_ranking_word_follows_sort_direction(direction, word):
    rows = [{"agent_id": "AGT-01", "avg_customer_rating": 4.5}]
    text, _ = format_answer("Which agent has the best average rating?", avg_plan(direction), rows)
    assert f"has the {word} average" in text


@pytest.mark.parametrize("direction,word", [("DESC", "most"), ("ASC", "fewest")])
def test_count_ranking_word_follows_sort_direction(direction, word):
    plan = {"aggregation": {"type": "count", "column": "*"}, "group_by": "agent_id",
            "order_by": {"column": "count_*", "direction": direction}, "limit": 1}
    text, _ = format_answer("Which agent has tickets?", plan, [{"agent_id": "AGT-01", "count_*": 3}])
    assert f"has the {word}, with 3 tickets" in text


def test_direction_falls_back_to_question_wording_without_order_by():
    plan = {"aggregation": {"type": "avg", "column": "customer_rating"}, "group_by": "agent_id"}
    rows = [{"agent_id": "AGT-01", "avg_customer_rating": 4.5}]
    assert "highest" in format_answer("Which agent has the highest average rating?", plan, rows)[0]
    assert "lowest" in format_answer("Which agent has the lowest average rating?", plan, rows)[0]


def test_regex_end_to_end_highest_and_lowest(db_path, regex_mode):
    hi, _ = answer_question("Which agent has the highest average rating?", str(db_path))
    lo, _ = answer_question("Which agent has the lowest average rating?", str(db_path))
    assert hi.startswith(f"{avg_by_agent.idxmax()} ") and "highest average" in hi
    assert lo.startswith(f"{avg_by_agent.idxmin()} ") and "lowest average" in lo


# --- regex parser: answer correctly or refuse, never answer a simpler question --------

def test_q6_extra_filter_is_refused_not_answered_with_total(db_path, regex_mode):
    # was: "1953 tickets match" (all resolved tickets) for a Billing-only question
    text, rows = answer_question("How many resolved tickets are in the Billing category?", str(db_path))
    assert text.startswith("I had trouble answering that")
    assert "billing" in text.lower() and rows == []
    assert "1953" not in text


def test_q17_per_agent_breakdown_is_answered_as_groups(db_path, regex_mode):
    # was: "1953 tickets match" (a single total) for a per-agent question
    _, rows = answer_question("How many resolved tickets per agent?", str(db_path))
    gold = df[df.status == "Resolved"].groupby("agent_id").size().to_dict()
    assert {r["agent_id"]: r["count_*"] for r in rows} == gold


def test_q30_category_ranking_is_answered_for_category_not_agent(db_path, regex_mode):
    # was: "AGT-08 (Agent) has the lowest average, at 3.14" for a category question
    text, _ = answer_question("Which category has the lowest average customer rating?", str(db_path))
    by_cat = df.groupby("category").customer_rating.mean()
    assert text.startswith(f"{by_cat.idxmin()} (Category) has the lowest average, at {by_cat.min():.2f}")
    assert "AGT-" not in text


@pytest.mark.parametrize("q", [
    "How many high priority tickets are unresolved?",
    "How many unresolved tickets were created this month?",
    "How many unresolved tickets in the Technical category?",
    "Which agent resolved the most critical tickets?",
])
def test_extra_qualifiers_are_refused(q):
    plan = fallback_regex_parser(q)
    assert set(plan) == {"error"}


def test_supported_phrasings_still_map():
    assert fallback_regex_parser("How many tickets are unresolved?")["aggregation"]["type"] == "count"
    assert fallback_regex_parser("How many critical tickets are unresolved?")["filters"][0]["value"] == "Critical"
    assert fallback_regex_parser("Which agent resolved the most tickets?")["group_by"] == "agent_id"
