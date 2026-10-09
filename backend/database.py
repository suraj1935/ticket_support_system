import sqlite3
import pandas as pd
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "support_tickets.csv"
DB_PATH = BASE_DIR / "tickets.db"

def init_db_from_csv():
    """Reads the CSV and initializes the SQLite database if it doesn't exist."""
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} not found.")
        return

    print("Initializing database from CSV...")
    df = pd.read_csv(CSV_PATH)
    
    # Convert created_at to datetime to ensure proper sorting and filtering if needed
    df['created_at'] = pd.to_datetime(df['created_at'])
    
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("tickets", conn, if_exists="replace", index=False)
    conn.close()
    print("Database initialization complete.")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_ticket_count():
    """Returns the total number of tickets in the database."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    conn.close()
    return count

def get_anomalies():
    """
    Detects and flags anomalies:
    1. Unresolved critical tickets.
    2. Abnormally long resolution times (> 48 hours).
    3. Very low ratings (1).
    """
    conn = get_db_connection()
    anomalies = []
    
    # 1. Unresolved Critical Tickets
    query_unresolved_critical = """
        SELECT *, 'Unresolved Critical Ticket' as anomaly_reason 
        FROM tickets 
        WHERE priority = 'Critical' AND status != 'Resolved'
    """
    df_critical = pd.read_sql_query(query_unresolved_critical, conn)
    
    # 2. Abnormally long resolution times (> 48 hours)
    query_long_resolution = """
        SELECT *, 'Abnormally Long Resolution (>48 hrs)' as anomaly_reason 
        FROM tickets 
        WHERE resolution_time_hrs > 48
    """
    df_long = pd.read_sql_query(query_long_resolution, conn)
    
    # 3. Very low ratings (rating = 1)
    query_low_rating = """
        SELECT *, 'Very Low Customer Rating (1 star)' as anomaly_reason 
        FROM tickets 
        WHERE customer_rating = 1
    """
    df_low = pd.read_sql_query(query_low_rating, conn)
    
    conn.close()
    
    # Combine and deduplicate (keep the first/most important anomaly reason per ticket)
    df_anomalies = pd.concat([df_critical, df_long, df_low], ignore_index=True)
    df_anomalies = df_anomalies.drop_duplicates(subset=['ticket_id'], keep='first')
    
    # Replace NaN/NaT with None for clean JSON serialization
    df_anomalies = df_anomalies.where(pd.notnull(df_anomalies), None)
    
    # Convert created_at to string if it's a datetime object
    if 'created_at' in df_anomalies.columns:
        df_anomalies['created_at'] = df_anomalies['created_at'].astype(str)

    records = df_anomalies.to_dict(orient="records")
    
    # Final pass: replace any remaining float NaN that sneaked through
    import math
    cleaned = []
    for row in records:
        cleaned.append({
            k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in row.items()
        })
    return cleaned

if __name__ == "__main__":
    init_db_from_csv()
