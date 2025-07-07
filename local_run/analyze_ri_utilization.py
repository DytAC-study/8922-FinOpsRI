# analyze_ri_utilization.py – Analyze RI usage and classify by status/expiry

import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sqlite3
from collections import defaultdict

# Load .env variables
load_dotenv()

# Thresholds and default configurations
MIN_UTILIZATION_THRESHOLD = float(os.getenv("MIN_UTILIZATION_THRESHOLD", 60))
EXPIRY_WARNING_DAYS = int(os.getenv("EXPIRY_WARNING_DAYS", 30))
ANALYSIS_WINDOW_DAYS = int(os.getenv("ANALYSIS_WINDOW_DAYS", 7))
UNDERUTILIZED_DAYS_THRESHOLD = int(os.getenv("UNDERUTILIZED_DAYS_THRESHOLD", 3))
UNUSED_DAYS_THRESHOLD = int(os.getenv("UNUSED_DAYS_THRESHOLD", 3))
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "eastus")
DEFAULT_SKU = os.getenv("DEFAULT_SKU", "Standard_DS1_v2")
ANALYSIS_MODE = os.getenv("ANALYSIS_MODE", "db")  # "db" or "json"

now = datetime.now()
today_str = now.strftime("%Y-%m-%d")
output_path = f"data/ri_utilization_summary_{today_str}.json"
results = []

def generate_alert(underutilized_days, unused_days):
    """
    Generate alert string based on thresholds.
    """
    if unused_days >= UNUSED_DAYS_THRESHOLD:
        return f"This RI has not been used for {unused_days} consecutive days."
    if underutilized_days >= UNDERUTILIZED_DAYS_THRESHOLD:
        return f"This RI has been underutilized for {underutilized_days} consecutive days."
    return ""

if ANALYSIS_MODE == "db":
    input_path = "ri_data.db"
    conn = sqlite3.connect(input_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT subscription_id, resource_id, usage_quantity, usage_start, email_recipient
        FROM ri_usage
        ORDER BY subscription_id, resource_id, usage_start
    """)
    records = cursor.fetchall()
    conn.close()

    # Group usage by (subscription_id, RI id)
    data_map = defaultdict(list)
    for sub_id, resource_id, qty, start, email in records:
        key = (sub_id, resource_id)
        data_map[key].append({
            "start": start,
            "quantity": qty,
            "email": email
        })

    # Analyze recent usage for each RI
    for (sub_id, resource_id), usage_list in data_map.items():
        recent_days = usage_list[-ANALYSIS_WINDOW_DAYS:]
        last_usage = recent_days[-1] if recent_days else {"quantity": None}
        qty = last_usage.get("quantity")

        # Count categories across analysis window
        underutilized_days = sum(
            1 for d in recent_days if d["quantity"] is not None and 0 < d["quantity"] < MIN_UTILIZATION_THRESHOLD
        )
        unused_days = sum(1 for d in recent_days if d["quantity"] == 0)
        missing_days = sum(1 for d in recent_days if d["quantity"] is None)

        # Classify current status
        if qty is None:
            status = "missing_data"
        elif qty == 0:
            status = "unused"
        elif qty < MIN_UTILIZATION_THRESHOLD:
            status = "underutilized"
        else:
            status = "healthy"

        # Check expiry
        purchase_date = now - timedelta(days=180)
        expiry_date = purchase_date + timedelta(days=365)
        days_remaining = (expiry_date - now).days

        if days_remaining < 0:
            expiry_status = "expired"
        elif days_remaining <= EXPIRY_WARNING_DAYS:
            expiry_status = "expiring_soon"
        else:
            expiry_status = "active"

        # Final record
        results.append({
            "subscription_id": sub_id,
            "ri_id": resource_id,
            "sku_name": DEFAULT_SKU,
            "region": DEFAULT_REGION,
            "purchase_date": purchase_date.strftime("%Y-%m-%d"),
            "term_months": 12,
            "utilization_percent": qty,
            "days_remaining": days_remaining,
            "status": status,
            "expiry_status": expiry_status,
            "underutilized_days": underutilized_days,
            "unused_days": unused_days,
            "missing_days": missing_days,
            "email_recipient": last_usage.get("email"),
            "alert": generate_alert(underutilized_days, unused_days)
        })

# Save result to file
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"[✅] Summary saved to {output_path}")
