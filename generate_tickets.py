"""Seeded synthetic support-ticket generator.

Writes support_tickets.csv with the same columns the app reads, and
data_truth/anomalies.csv listing every ticket that meets an anomaly rule,
so the anomaly service can be scored with precision and recall. The truth file applies the
rule definitions above to the final data (the `planted` column marks the ones injected on purpose).

Usage:  python generate_tickets.py --rows 2000 --seed 42 --as-of 2026-10-01
Everything below the constants is plain numpy/pandas, no outside data.
"""
import argparse
import pathlib
import numpy as np
import pandas as pd

# Set these to match the thresholds used in the anomaly service.
STALE_HOURS = 0            # unresolved Critical ticket older than this is "stale" (same rule as backend/database.py)
SLOW_RESOLUTION_HOURS = 48  # resolution slower than this is "slow"
LOW_RATING_MAX = 1          # rating at or below this is "low"

CATEGORIES = {"Billing": 0.30, "Technical": 0.45, "General": 0.25}
PRIORITIES = {"Low": 0.28, "Medium": 0.34, "High": 0.26, "Critical": 0.12}
# median resolution hours by priority (urgent tickets get fixed faster)
RES_MEDIAN = {"Low": 9.0, "Medium": 7.0, "High": 5.0, "Critical": 4.0}
RESP_MEDIAN = {"Low": 3.0, "Medium": 2.0, "High": 1.0, "Critical": 0.6}

SUMMARIES = {
    "Billing": ["Incorrect charge on invoice", "Refund not processed", "Double payment on subscription",
                "Invoice missing GST details", "Coupon code not applied", "Card declined at renewal"],
    "Technical": ["Login failure after update", "API timeout in production", "Dashboard not loading",
                  "Webhook events delayed", "Export to CSV fails", "Two-factor code not arriving"],
    "General": ["Request for product docs", "How to change account owner", "Feature request: dark mode",
                "Question about data retention", "Need onboarding session", "Update company address"],
}


def pick(rng, probs, n):
    keys = list(probs)
    return rng.choice(keys, size=n, p=[probs[k] for k in keys])


def generate(rows, seed, as_of):
    rng = np.random.default_rng(seed)
    as_of = pd.Timestamp(as_of)
    agents = [f"AGT-{i:02d}" for i in range(1, 13)]
    skill = dict(zip(agents, rng.normal(0, 0.5, len(agents))))   # + is better
    skill[agents[7]] = -2.4   # one clearly weak agent, so "lowest rated agent" has a clear answer
    skill[agents[11]] = 1.8   # and one strong one

    # created_at: last 12 months, weekday and business-hour heavy
    days = rng.integers(1, 366, rows)
    base = as_of.normalize() - pd.to_timedelta(days, unit="D")
    hours = np.clip(rng.normal(13, 3.5, rows), 0, 23.9)
    created = base + pd.to_timedelta(hours, unit="h")
    created = created.floor("min")

    cat = pick(rng, CATEGORIES, rows)
    pri = pick(rng, PRIORITIES, rows)
    agent = rng.choice(agents, rows)
    sk = np.array([skill[a] for a in agent])

    resp = np.array([RESP_MEDIAN[p] for p in pri]) * np.exp(rng.normal(0, 0.6, rows) - 0.15 * sk)
    res = np.array([RES_MEDIAN[p] for p in pri]) * np.exp(rng.normal(0, 0.7, rows) - 0.2 * sk)
    res = np.maximum(res, resp + 0.2)

    age_h = (as_of - created) / pd.Timedelta(hours=1)
    status = np.empty(rows, dtype=object)
    for i in range(rows):
        recent = age_h[i] < 24 * 21
        p_unres = 0.22 if recent else 0.0        # only recent tickets can still be open
        if rng.random() < p_unres:
            status[i] = rng.choice(["Open", "Escalated"], p=[0.7, 0.3])
        else:
            status[i] = "Resolved"
    # tickets cannot be resolved faster than they are old
    res = np.where((status == "Resolved") & (res > age_h), age_h * rng.uniform(0.4, 0.9, rows), res)

    # rating: depends on speed and agent skill, only for resolved tickets
    score = 4.7 + 0.45 * sk - 0.10 * np.log1p(np.maximum(res, 0)) * 2 + rng.normal(0, 0.7, rows)
    rating = np.clip(np.rint(score), 1, 5).astype(float)

    df = pd.DataFrame({
        "ticket_id": [f"TKT-{i + 1:04d}" for i in range(rows)],
        "created_at": created, "category": cat, "priority": pri, "status": status,
        "response_time_hrs": np.round(resp, 1), "resolution_time_hrs": np.round(res, 1),
        "agent_id": agent, "customer_rating": rating,
        "issue_summary": [rng.choice(SUMMARIES[c]) for c in cat],
    })
    unresolved = df.status != "Resolved"
    df.loc[unresolved, ["resolution_time_hrs", "customer_rating"]] = np.nan

    # --- plant anomalies with known labels -------------------------------------------
    truth = []
    resolved_idx = df.index[~unresolved]
    for i in rng.choice(resolved_idx, size=int(rows * 0.025), replace=False):
        df.loc[i, "resolution_time_hrs"] = round(float(rng.uniform(SLOW_RESOLUTION_HOURS * 1.1, SLOW_RESOLUTION_HOURS * 3)), 1)
        truth.append((df.loc[i, "ticket_id"], "slow_resolution"))
    for i in rng.choice(resolved_idx, size=int(rows * 0.02), replace=False):
        df.loc[i, "customer_rating"] = float(rng.integers(1, LOW_RATING_MAX + 1))
        truth.append((df.loc[i, "ticket_id"], "low_rating"))
    for k in range(int(rows * 0.012)):
        i = rng.integers(0, rows)
        df.loc[i, ["status", "priority", "resolution_time_hrs", "customer_rating"]] = [
            rng.choice(["Open", "Escalated"]), rng.choice(["High", "Critical"]), np.nan, np.nan]
        df.loc[i, "created_at"] = (as_of - pd.Timedelta(hours=float(rng.uniform(STALE_HOURS * 1.5, 24 * 14)))).floor("min")
        truth.append((df.loc[i, "ticket_id"], "stale_high_priority"))
    planted = {(t, k) for t, k in truth}
    created_ts = pd.to_datetime(df["created_at"])
    age = (as_of - created_ts) / pd.Timedelta(hours=1)
    res_ok = df.status == "Resolved"
    rules = {
        "stale_high_priority": (~res_ok) & (df.priority == "Critical") & (age > STALE_HOURS),
        "slow_resolution": res_ok & (df.resolution_time_hrs > SLOW_RESOLUTION_HOURS),
        "low_rating": res_ok & (df.customer_rating <= LOW_RATING_MAX),
    }
    truth = [(df.loc[i, "ticket_id"], k, (df.loc[i, "ticket_id"], k) in planted)
             for k, m in rules.items() for i in df.index[m.fillna(False)]]
    df["created_at"] = created_ts.dt.strftime("%Y-%m-%d %H:%M")
    df["customer_rating"] = df["customer_rating"].astype("Int64")
    return df.sort_values("created_at").reset_index(drop=True), pd.DataFrame(truth, columns=["ticket_id", "anomaly_type", "planted"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", default="2026-10-01")
    ap.add_argument("--out", default="support_tickets.csv")
    a = ap.parse_args()
    data, truth = generate(a.rows, a.seed, a.as_of)
    data.to_csv(a.out, index=False)
    pathlib.Path("data_truth").mkdir(exist_ok=True)
    truth.to_csv("data_truth/anomalies.csv", index=False)
    print(f"wrote {len(data)} tickets to {a.out}; anomalies by rule: {truth.anomaly_type.value_counts().to_dict()}")
