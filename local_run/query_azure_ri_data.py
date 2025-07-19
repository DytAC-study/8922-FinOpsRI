# query_azure_ri_data.py – Generate daily mock RI utilization data for local testing

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
import random

load_dotenv()

OUTPUT_DIR = "data"
Path(OUTPUT_DIR).mkdir(exist_ok=True)

# --- Configuration from environment variables (consistent with Azure Functions) ---
# These are used for generating mock data properties
DEFAULT_TERM_MONTHS = int(os.getenv("DEFAULT_TERM_MONTHS", "12"))
# MOCK_PURCHASE_DATE_OFFSET_DAYS: Used to set a mock purchase date for RIs.
# This ensures a plausible purchase date for the mock RIs.
MOCK_PURCHASE_DATE_OFFSET_DAYS = int(os.getenv("MOCK_PURCHASE_DATE_OFFSET_DAYS", "180")) # e.g., purchase 180 days ago
# ANALYSIS_PERIOD_DAYS: Number of days for which to generate mock daily data.
# This should align with the ANALYSIS_PERIOD_DAYS in analyze_ri_utilization.py.
ANALYSIS_PERIOD_DAYS = int(os.getenv("ANALYSIS_PERIOD_DAYS", "30")) 
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "eastus")
DEFAULT_SKU = os.getenv("DEFAULT_SKU", "Standard_DS1_v2")

# Mock RIs and their associated emails
MOCK_RIS = [
    {"id": "ri-mock-001", "sku": "Standard_D2_v3", "region": "eastus", "email": "devteam@example.com"},
    {"id": "ri-mock-002", "sku": "Standard_E4_v3", "region": "westus", "email": "finops@example.com"},
    {"id": "ri-mock-003", "sku": "Standard_B2s", "region": "centralus", "email": "devteam@example.com"},
    {"id": "ri-mock-004", "sku": "Standard_D4_v3", "region": "eastus", "email": "finops@example.com"},
    {"id": "ri-mock-005", "sku": "Standard_B4ms", "region": "westus", "email": "devteam@example.com"},
]

MOCK_SUBSCRIPTIONS = ["sub-mock-a", "sub-mock-b"]

def generate_mock_daily_utilization(ri_id, start_date, end_date):
    """Generates mock daily utilization data for a single RI over a date range."""
    daily_data = []
    current_date = start_date
    while current_date <= end_date:
        # Simulate varying utilization: mostly healthy, some underutilized, some unused
        util_percent = random.choice([
            random.uniform(85, 100), # Healthy utilization
            random.uniform(20, 79),  # Underutilized
            0.0,                     # Unused
            random.uniform(85, 100), # Healthy
            random.uniform(85, 100)  # Healthy
        ])
        daily_data.append(round(util_percent, 2))
        current_date += timedelta(days=1)
    return daily_data

def main():
    today = datetime.utcnow().date()
    
    # Define the period for which to generate daily data
    # This aligns with how Azure Function's analyze_ri_utilization.py expects data
    # Generate data up to yesterday to simulate daily data collection
    analysis_end_date = today - timedelta(days=1) 
    analysis_start_date = analysis_end_date - timedelta(days=ANALYSIS_PERIOD_DAYS - 1)

    all_daily_records = []

    for sub_id in MOCK_SUBSCRIPTIONS:
        for mock_ri in MOCK_RIS:
            ri_id = mock_ri["id"]
            sku_name = mock_ri["sku"]
            region = mock_ri["region"]
            email_recipient = mock_ri["email"]

            # Mock purchase date for this RI (consistent for its lifetime)
            # Ensure purchase_date is before analysis_start_date for realistic scenarios
            mock_purchase_date = analysis_start_date - timedelta(days=MOCK_PURCHASE_DATE_OFFSET_DAYS)
            
            daily_util_data = generate_mock_daily_utilization(ri_id, analysis_start_date, analysis_end_date)
            
            current_date_for_record = analysis_start_date
            for util_qty in daily_util_data:
                record = {
                    "subscription_id": sub_id,
                    "resource_id": ri_id,
                    "usage_quantity": util_qty,
                    "report_date": current_date_for_record.strftime("%Y-%m-%d"), # Daily report date
                    "email_recipient": email_recipient,
                    "sku_name": sku_name,
                    "region": region,
                    "term_months": DEFAULT_TERM_MONTHS, # Use default term months
                    "purchase_date": mock_purchase_date.strftime("%Y-%m-%d") # Consistent purchase date for this RI
                }
                all_daily_records.append(record)
                current_date_for_record += timedelta(days=1)

    # Save the generated daily data to a JSON file
    file_path = os.path.join(OUTPUT_DIR, f"azure_ri_usage_daily_summary_{today.strftime('%Y-%m-%d')}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(all_daily_records, f, indent=2)
    print(f"[✅] Daily mock RI utilization data saved to {file_path}")

if __name__ == "__main__":
    main()
