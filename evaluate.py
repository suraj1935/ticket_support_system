import pandas as pd
from backend.database import get_anomalies

def evaluate_anomalies():
    print("--- Anomaly Evaluation ---")
    truth_df = pd.read_csv("data_truth/anomalies.csv")
    truth_set = set(zip(truth_df["ticket_id"], truth_df["anomaly_type"]))

    service_anomalies = get_anomalies()
    REASON_TO_TYPE = {
        "Unresolved Critical Ticket": "stale_high_priority",
        "Abnormally Long Resolution (>48 hrs)": "slow_resolution",
        "Very Low Customer Rating (1 star)": "low_rating"
    }
    service_set = set((a["ticket_id"], REASON_TO_TYPE.get(a.get("anomaly_reason"), "unknown")) for a in service_anomalies)

    rules = ["stale_high_priority", "slow_resolution", "low_rating"]
    for rule in rules:
        truth_rule = {t for t, r in truth_set if r == rule}
        service_rule = {t for t, r in service_set if r == rule}

        tp = len(truth_rule & service_rule)
        fp = len(service_rule - truth_rule)
        fn = len(truth_rule - service_rule)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        print(f"Rule: {rule}")
        print(f"  Precision: {precision:.2f}")
        print(f"  Recall:    {recall:.2f}")
    print()

def evaluate_questions():
    print("--- Question Evaluation (Gold Answers from Pandas) ---")
    df = pd.read_csv("support_tickets.csv")

    # 1. How many tickets are unresolved?
    unresolved = len(df[df["status"] != "Resolved"])
    print(f"How many tickets are unresolved? {unresolved}")

    # 2. How many tickets are open?
    open_t = len(df[df["status"] == "Open"])
    print(f"How many tickets are open? {open_t}")

    # 3. How many critical tickets are unresolved?
    crit_unresolved = len(df[(df["priority"] == "Critical") & (df["status"] != "Resolved")])
    print(f"How many critical tickets are unresolved? {crit_unresolved}")

    # 4. Which agent resolved the most tickets?
    # groupby agent_id where status == 'Resolved'
    if not df[df["status"] == "Resolved"].empty:
        top_agent = df[df["status"] == "Resolved"].groupby("agent_id").size().idxmax()
        top_agent_count = df[df["status"] == "Resolved"].groupby("agent_id").size().max()
        print(f"Which agent resolved the most tickets? {top_agent} ({top_agent_count})")

    # 5. Which agent has the lowest average rating?
    if not df["customer_rating"].dropna().empty:
        low_agent = df.dropna(subset=["customer_rating"]).groupby("agent_id")["customer_rating"].mean().idxmin()
        low_agent_avg = df.dropna(subset=["customer_rating"]).groupby("agent_id")["customer_rating"].mean().min()
        print(f"Which agent has the lowest average rating? {low_agent} ({low_agent_avg:.2f})")

    # 6. What is the average customer rating?
    avg_rating = df["customer_rating"].mean()
    print(f"What is the average customer rating? {avg_rating:.2f}")

    # 7. How many tickets per priority?
    priority_counts = df.groupby("priority").size().to_dict()
    print(f"How many tickets per priority? {priority_counts}")

if __name__ == '__main__':
    evaluate_anomalies()
    evaluate_questions()
