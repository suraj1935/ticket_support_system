"""Question evaluation: 30 in-scope questions with pandas gold answers + 5 out-of-scope.

Usage:  python eval/run_eval.py            # regex mode, plus Ollama mode if it is running
Writes eval/results.md. Each question is scored as an exact match on the answer
(numbers compared at the 2-decimal precision the system prints).
"""
import contextlib
import io
import pathlib
import re
import sys
import tempfile

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backend.database as database  # noqa: E402
import backend.llm as llm  # noqa: E402

OLLAMA_URL = "http://localhost:11434"
df = pd.read_csv(ROOT / "support_tickets.csv")
df["created_at"] = pd.to_datetime(df["created_at"])
res = df[df.status == "Resolved"]


def r2(x):
    return round(float(x), 2)


def top(series, largest=True):
    """idxmax/idxmin, but fail loudly if the gold answer is tied."""
    best = series.max() if largest else series.min()
    winners = series[series == best]
    assert len(winners) == 1, f"tied gold answer: {winners}"
    return winners.index[0], best


def ent(series, largest=True, dec=False):
    k, v = top(series, largest)
    return ("entity", k, r2(v) if dec else int(v), "most" if largest else "lowest" if dec else "")


def grp(series, dec=False):
    return ("groups", {k: (r2(v) if dec else int(v)) for k, v in series.items()})


def between(a, b):
    return df[(df.created_at >= a) & (df.created_at <= pd.Timestamp(b) + pd.Timedelta(hours=23, minutes=59, seconds=59))]


# (category, question, gold)
QUESTIONS = [
    ("count", "How many tickets are there in total?", ("scalar", len(df))),
    ("count", "How many tickets are unresolved?", ("scalar", int((df.status != "Resolved").sum()))),
    ("count", "How many tickets are open?", ("scalar", int((df.status == "Open").sum()))),
    ("count", "How many critical tickets are unresolved?", ("scalar", int(((df.priority == "Critical") & (df.status != "Resolved")).sum()))),
    ("count", "How many tickets are escalated?", ("scalar", int((df.status == "Escalated").sum()))),
    ("count", "How many resolved tickets are in the Billing category?", ("scalar", int(((df.status == "Resolved") & (df.category == "Billing")).sum()))),
    ("average", "What is the average customer rating?", ("scalar", r2(df.customer_rating.mean()))),
    ("average", "What is the average resolution time in hours?", ("scalar", r2(df.resolution_time_hrs.mean()))),
    ("average", "What is the average response time in hours?", ("scalar", r2(df.response_time_hrs.mean()))),
    ("average", "What is the average rating for Technical tickets?", ("scalar", r2(df[df.category == "Technical"].customer_rating.mean()))),
    ("average", "What is the average resolution time for critical tickets?", ("scalar", r2(df[df.priority == "Critical"].resolution_time_hrs.mean()))),
    ("group-by", "How many tickets per priority?", grp(df.groupby("priority").size())),
    ("group-by", "How many tickets per category?", grp(df.groupby("category").size())),
    ("group-by", "How many tickets per status?", grp(df.groupby("status").size())),
    ("group-by", "What is the average customer rating per category?", grp(df.groupby("category").customer_rating.mean(), dec=True)),
    ("group-by", "What is the average resolution time per priority?", grp(df.groupby("priority").resolution_time_hrs.mean(), dec=True)),
    ("group-by", "How many resolved tickets per agent?", grp(res.groupby("agent_id").size())),
    ("filter", "How many tickets have a customer rating of 1?", ("scalar", int((df.customer_rating == 1).sum()))),
    ("filter", "How many tickets have a resolution time over 48 hours?", ("scalar", int((df.resolution_time_hrs > 48).sum()))),
    ("filter", "How many high priority tickets are in the Technical category?", ("scalar", int(((df.priority == "High") & (df.category == "Technical")).sum()))),
    ("filter", "How many tickets have no customer rating?", ("scalar", int(df.customer_rating.isna().sum()))),
    ("date range", "How many tickets were created between 2026-01-01 and 2026-03-31?", ("scalar", len(between("2026-01-01", "2026-03-31")))),
    ("date range", "How many tickets were created after 2026-09-01?", ("scalar", int((df.created_at > pd.Timestamp("2026-09-01 23:59:59")).sum()))),
    ("date range", "How many tickets were created before 2025-12-01?", ("scalar", int((df.created_at < pd.Timestamp("2025-12-01")).sum()))),
    ("top agent", "Which agent resolved the most tickets?", ent(res.groupby("agent_id").size())),
    ("top agent", "Which agent has the lowest average rating?", ent(df.groupby("agent_id").customer_rating.mean(), largest=False, dec=True)),
    ("top agent", "Which agent has the highest average rating?", ent(df.groupby("agent_id").customer_rating.mean(), dec=True)),
    ("top category", "Which category has the most tickets?", ent(df.groupby("category").size())),
    ("top category", "Which category has the most unresolved tickets?", ent(df[df.status != "Resolved"].groupby("category").size())),
    ("top category", "Which category has the lowest average customer rating?", ent(df.groupby("category").customer_rating.mean(), largest=False, dec=True)),
]
assert len(QUESTIONS) == 30

OUT_OF_SCOPE = [
    ("comparison", "Compare the average resolution time of Billing tickets versus Technical tickets."),
    ("comparison", "Are critical tickets resolved faster than low priority tickets?"),
    ("trend", "What is the trend in ticket volume by month?"),
    ("median", "What is the median resolution time?"),
    ("percentile", "What is the 90th percentile of response time?"),
]


def nums(text):
    return re.findall(r"-?\d+(?:\.\d+)?", text)


def score(gold, answer, rows):
    """Return (ok, detail). Exact match on the answer."""
    kind = gold[0]
    if kind == "scalar":
        n = nums(answer)
        want = f"{gold[1]:.2f}" if isinstance(gold[1], float) else str(gold[1])
        return (bool(n) and n[0] == want), f"want {want}"
    if kind == "entity":
        _, name, val, word = gold
        want = f"{name} / {val:.2f}" if isinstance(val, float) else f"{name} / {val}"
        n = nums(answer)
        ok = answer.startswith(name) and bool(n) and r2(n[-1]) == r2(val)
        if ok and word == "lowest" and "highest" in answer or ok and word == "most" and "lowest" in answer:
            ok = False  # right entity, wrong direction label
        return ok, f"want {want}"
    if kind == "groups":
        gold_d = gold[1]
        try:
            got = {}
            for row in rows:
                items = list(row.items())
                got[items[0][1]] = r2(items[1][1]) if isinstance(items[1][1], float) else int(items[1][1])
        except Exception:
            return False, f"want {len(gold_d)} groups"
        return got == gold_d, f"want {len(gold_d)} groups"
    raise ValueError(kind)


def refused(answer, rows):
    a = answer.lower()
    return not rows and ("trouble" in a or "couldn't" in a or "cannot" in a or "not supported" in a)


def ollama_target():
    """Cloud model if OLLAMA_API_KEY is set (llm.call_ollama then uses it), else the local server."""
    if llm.OLLAMA_API_KEY:
        return True, f"Ollama Cloud {llm.OLLAMA_CLOUD_MODEL}", ""
    name = f"Ollama local {llm.OLLAMA_MODEL}"
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
    except Exception as e:
        return False, name, f"Ollama not reachable at {OLLAMA_URL} ({type(e).__name__})"
    names = [m.get("name", "") for m in tags.get("models", [])]
    if not any(n.startswith(llm.OLLAMA_MODEL) for n in names):
        return False, name, f"Ollama is running but {llm.OLLAMA_MODEL} is not pulled (have: {names})"
    return True, name, ""


def run_mode(mode, db_path):
    """Run all questions under one mode. Returns (in_scope_results, oos_results, llm_stats)."""
    stats = {"llm_calls": 0, "llm_no_reply": 0}
    llm.call_groq = lambda prompt: None
    if mode == "regex":
        llm.call_ollama = lambda prompt: None
    else:
        orig = ORIG_CALL_OLLAMA

        def counting(prompt):
            stats["llm_calls"] += 1
            out = orig(prompt)
            if out is None:
                stats["llm_no_reply"] += 1
            return out
        llm.call_ollama = counting

    def ask(q):
        with contextlib.redirect_stdout(io.StringIO()):
            return llm.answer_question(q, str(db_path))

    res_in = []
    for cat, q, gold in QUESTIONS:
        ans, rows = ask(q)
        ok, detail = score(gold, ans, rows)
        res_in.append(dict(cat=cat, q=q, ok=ok, want=detail, got=ans if not rows else f"{ans} [{len(rows)} rows]",
                           refused=refused(ans, rows)))
    res_out = []
    for cat, q in OUT_OF_SCOPE:
        ans, rows = ask(q)
        res_out.append(dict(cat=cat, q=q, refused=refused(ans, rows),
                            got=ans if not rows else f"{ans} [{len(rows)} rows: {rows[:2]}...]"))
    return res_in, res_out, stats


ORIG_CALL_OLLAMA = llm.call_ollama


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def main():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "tickets.db"
    database.DB_PATH = tmp
    database.init_db_from_csv()

    results = {}
    skipped = {}
    results["regex"] = run_mode("regex", tmp)
    up, oname, why = ollama_target()
    if up:
        results[oname] = run_mode("ollama", tmp)
    else:
        skipped[oname] = why

    out = ["# Question Evaluation Results", "",
           f"Dataset: `support_tickets.csv` ({len(df)} tickets, created_at {df.created_at.min():%Y-%m-%d} to {df.created_at.max():%Y-%m-%d}).",
           "Gold answers are computed with pandas directly from the CSV. Scoring is exact match on the answer "
           "(counts as integers, averages at the 2 decimals the system prints, group-by as the full {group: value} set, "
           "top-N as entity + value; a right entity with the wrong direction word, e.g. \"lowest\" for a highest-average question, fails).",
           "Reproduce: `python eval/run_eval.py`.", ""]

    cats = list(dict.fromkeys(c for c, _, _ in QUESTIONS))
    modes = list(results)
    out += ["## Overall", "", "| Category | n | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]
    for c in cats:
        n = sum(1 for x, _, _ in QUESTIONS if x == c)
        cells = [f"{sum(1 for r in results[m][0] if r['cat'] == c and r['ok'])}/{n}" for m in modes]
        out.append(f"| {c} | {n} | " + " | ".join(cells) + " |")
    tot = [sum(r["ok"] for r in results[m][0]) for m in modes]
    out.append("| **All in-scope** | 30 | " + " | ".join(f"**{t}/30 ({t / 30:.1%})**" for t in tot) + " |")
    out.append("")
    out += ["### Correct vs refused vs confidently wrong (in-scope, n=30)", "",
            "Refused = no data and an error message (including the system failing to build a valid plan). "
            "Confidently wrong = a normal-looking answer that does not match the gold answer.", "",
            "| Mode | Correct | Refused | Confidently wrong |", "|---|---|---|---|"]
    for m in modes:
        rs = results[m][0]
        c = sum(r["ok"] for r in rs)
        rf = sum(1 for r in rs if not r["ok"] and r["refused"])
        out.append(f"| {m} | {c} | {rf} | {30 - c - rf} |")
    out.append("")
    for m, why in skipped.items():
        out.append(f"- **{m}: NOT RUN.** {why}. No numbers are reported for this mode.")
    for m in modes:
        s = results[m][2]
        if m != "regex":
            out.append(f"- {m}: {s['llm_calls']} LLM calls, {s['llm_no_reply']} returned nothing (these fall back to the regex parser, so a wrong answer in this mode may come from the fallback).")
    out.append("")

    out += ["## Out-of-scope questions (5)", "",
            "A refusal is the safe outcome (no data, error message). Anything else is an answer the system "
            "was never designed to give, so it is recorded as a wrong answer.", "",
            "| Type | Question | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]
    for i, (cat, q) in enumerate(OUT_OF_SCOPE):
        cells = []
        for m in modes:
            r = results[m][1][i]
            cells.append("Refused" if r["refused"] else f"WRONG ANSWER: {esc(r['got'])}")
        out.append(f"| {cat} | {esc(q)} | " + " | ".join(cells) + " |")
    ref = [sum(r["refused"] for r in results[m][1]) for m in modes]
    out.append("| **Refused** | | " + " | ".join(f"**{x}/5**" for x in ref) + " |")
    out.append("")

    for m in modes:
        out += [f"## Per-question results: {m}", "", "| # | Category | Question | Result | Gold | System answer |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(results[m][0], 1):
            out.append(f"| {i} | {r['cat']} | {esc(r['q'])} | {'PASS' if r['ok'] else ('REFUSED' if r['refused'] else 'FAIL')} | {esc(r['want'])} | {esc(r['got'])} |")
        out.append("")
    (ROOT / "eval" / "results.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
