# query_azure_ri_data.py – Extract flat RI utilization summary from Azure usage and tags

import os
import json
from datetime import datetime, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.consumption import ConsumptionManagementClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

OUTPUT_DIR = "data"
DEFAULT_TERM_MONTHS = 12
DAYS_BEFORE_TODAY = 180

def fetch_subscriptions():
    credential = DefaultAzureCredential()
    client = SubscriptionClient(credential)
    return [sub.subscription_id for sub in client.subscriptions.list()]

def fetch_tagged_emails(subscription_id):
    credential = DefaultAzureCredential()
    client = ResourceManagementClient(credential, subscription_id)
    resources = client.resources.list(filter="tagName eq 'email'")
    email_map = {}
    for res in resources:
        email = res.tags.get("email") if res.tags else None
        if email:
            email_map[res.id.lower()] = email
    return email_map

def fetch_usage_details(subscription_id):
    credential = DefaultAzureCredential()
    client = ConsumptionManagementClient(credential, subscription_id)
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=7)  # 最近 7 天平均
    usage = client.usage_details.list(
        expand="properties/meterDetails",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )
    usage_map = {}
    for item in usage:
        props = item.additional_properties.get("properties", {})
        resource_id = props.get("instanceId", "").lower()
        quantity = props.get("quantity", 0)
        meter = props.get("meterDetails", {})
        usage_map.setdefault(resource_id, []).append({
            "quantity": quantity,
            "region": meter.get("meterRegion", "eastus"),
            "sku": meter.get("meterName", "Standard_DS1_v2")
        })
    return usage_map

def main():
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    today = datetime.utcnow().date()
    file_path = os.path.join(OUTPUT_DIR, f"azure_ri_usage_summary_{today.isoformat()}.json")

    all_flat_records = []

    subscriptions = fetch_subscriptions()
    print(f"[🔎] Found {len(subscriptions)} subscription(s)")

    for sub_id in subscriptions:
        print(f"[📦] Processing subscription: {sub_id}")
        email_tags = fetch_tagged_emails(sub_id)
        usage = fetch_usage_details(sub_id)

        for resource_id, daily_records in usage.items():
            avg_util = sum([r["quantity"] for r in daily_records]) / len(daily_records)
            sample = daily_records[-1]  # Get region + sku from last record

            flat_record = {
                "subscription_id": sub_id,
                "ri_id": resource_id,
                "sku_name": sample.get("sku"),
                "region": sample.get("region"),
                "purchase_date": (today - timedelta(days=DAYS_BEFORE_TODAY)).isoformat(),
                "term_months": DEFAULT_TERM_MONTHS,
                "utilization_percent": round(avg_util, 2),
                "email_recipient": email_tags.get(resource_id, "noreply@example.com")
            }
            all_flat_records.append(flat_record)

    with open(file_path, "w") as f:
        json.dump(all_flat_records, f, indent=2)
    print(f"[✅] Data saved to {file_path}")

if __name__ == "__main__":
    main()
