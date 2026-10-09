def format_answer(question: str, plan: dict, rows: list) -> tuple[str, list]:
    """Single source of truth for turning a plan + result into an answer string and UI rows."""
    
    agg = plan.get("aggregation")
    group_by = plan.get("group_by")
    
    def _fmt_num(v) -> str:
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    def _col_label(col: str) -> str:
        return {
            "customer_rating": "customer rating",
            "response_time_hrs": "response time",
            "resolution_time_hrs": "resolution time",
            "*": "tickets",
        }.get(col, col.replace("_", " "))

    def _group_label(col: str) -> str:
        return {
            "agent_id": "Agent",
            "category": "Category",
            "priority": "Priority",
            "status": "Status",
        }.get(col, col)

    def _sort_direction(q: str, plan: dict) -> str:
        """The plan's order_by decides; if absent, fall back to the wording of the question."""
        direction = str((plan.get("order_by") or {}).get("direction", "")).upper()
        if direction in ("ASC", "DESC"):
            return direction
        low = any(w in q.lower() for w in ("lowest", "least", "fewest", "worst", "smallest"))
        return "ASC" if low else "DESC"

    def _is_ranking_question(q: str) -> bool:
        q = q.lower()
        return any(w in q for w in ("which", "who", "top", "most", "least", "lowest", "highest", "best", "worst"))
        
    # ---- Case 1: scalar aggregation (count / mean / sum / min / max), no group_by
    if agg and not group_by:
        if not rows:
            return "No tickets match this query.", []
            
        row = rows[0]
        # the scalar value is the first value in the dict
        scalar = list(row.values())[0] if row else None
        
        col = _col_label(agg["column"])
        agg_type = agg["type"].lower()
        
        if agg_type == "count":
            n = int(scalar) if scalar is not None else 0
            return f"{n} ticket{'s' if n != 1 else ''} match this query.", []
        if agg_type in ("avg", "mean"):
            return f"The average {col} is {_fmt_num(scalar)}.", []
        if agg_type == "sum":
            return f"The total {col} is {_fmt_num(scalar)}.", []
        if agg_type == "min":
            return f"The minimum {col} is {_fmt_num(scalar)}.", []
        if agg_type == "max":
            return f"The maximum {col} is {_fmt_num(scalar)}.", []
        return f"Result: {_fmt_num(scalar)}.", []

    # ---- Case 2: group-by with single row (ranking question)
    if group_by and rows and len(rows) == 1:
        row = rows[0]
        group_val = row.get(group_by, "Unknown")
        
        metric_val = None
        for k, v in row.items():
            if k != group_by:
                metric_val = v
                break
                
        group_label = _group_label(group_by)

        if _is_ranking_question(question):
            # "Which agent has ..." - return a sentence and clear rows
            descending = _sort_direction(question, plan) == "DESC"
            if agg and agg["type"].lower() == "count":
                n = int(metric_val) if metric_val is not None else 0
                word = "most" if descending else "fewest"
                return f"{group_val} ({group_label}) has the {word}, with {n} ticket{'s' if n != 1 else ''}.", []
            if agg and agg["type"].lower() in ("avg", "mean"):
                word = "highest" if descending else "lowest"
                return f"{group_val} ({group_label}) has the {word} average, at {_fmt_num(metric_val)}.", []
            return f"{group_val}: {_fmt_num(metric_val)}.", []
            
        # otherwise it's a group-by that happened to return one row
        return f"{group_label} {group_val}: {_fmt_num(metric_val)}.", rows

    # ---- Case 3: group-by with multiple rows
    if group_by and rows:
        return f"{len(rows)} groups found.", rows

    # ---- Case 4: list / filter result
    if rows:
        n = len(rows)
        return f"Found {n} matching record{'s' if n != 1 else ''}.", rows

    # ---- Case 5: nothing matched
    return "No tickets match this query.", []
