import logging
import os
import json
import csv # Import csv module
from datetime import datetime, timedelta
import azure.functions as func
from azure.storage.blob import BlobClient
import io # Import io for in-memory CSV writing

# Import the core logic from the adjacent file
from .query_azure_ri_data import fetch_subscriptions, fetch_tagged_emails, fetch_usage_details

# Blob Storage Configuration (from Function App Settings)
# 'AzureWebJobsStorage' is the default connection string for the Function App's storage.
STORAGE_ACCOUNT_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
RAW_USAGE_CONTAINER_NAME = "ri-usage-raw" # Container to store raw RI usage data CSVs

def main(mytimer: func.TimerRequest):
    """
    Azure Function entry point for querying RI data.
    Triggered by a timer (e.g., daily).
    """
    utc_timestamp = datetime.utcnow().isoformat()
    logging.info(f'Python timer trigger function started at {utc_timestamp}')

    today = datetime.utcnow().date()
    # Define the output file name for the CSV blob
    file_name = f"azure_ri_usage_summary_{today.isoformat()}.csv" # Changed to .csv

    all_flat_records = []

    try:
        # Fetch Azure subscriptions
        subscriptions = fetch_subscriptions()
        logging.info(f"[🔎] Found {len(subscriptions)} subscription(s).")

        # Iterate through each subscription to fetch RI usage and associated emails
        for sub_id in subscriptions:
            logging.info(f"[📦] Processing subscription: {sub_id}")
            email_tags = fetch_tagged_emails(sub_id)
            usage = fetch_usage_details(sub_id)

            # Flatten the usage data and enrich with email recipients
            for resource_id, daily_records in usage.items():
                if not daily_records:
                    continue # Skip if no daily records found for this RI

                # Calculate average utilization (assuming 'quantity' is utilization metric)
                # Ensure daily_records has items before calculating sum/len
                if daily_records:
                    avg_util = sum([r["quantity"] for r in daily_records]) / len(daily_records)
                    sample = daily_records[-1] # Get region and SKU from the most recent record
                else:
                    avg_util = 0.0
                    sample = {} # Handle empty case

                flat_record = {
                    "subscription_id": sub_id,
                    "ri_id": resource_id,
                    "sku_name": sample.get("sku", "N/A"), # Use N/A for default
                    "region": sample.get("region", "N/A"), # Use N/A for default
                    # These dates are placeholders for initial sample data.
                    # In a real scenario, you would fetch actual purchase and term details.
                    "purchase_date": (today - timedelta(days=180)).isoformat(), # Example: 6 months ago
                    "term_months": 12, # Example: 12-month term
                    "utilization_percent": round(avg_util, 2),
                    "email_recipient": email_tags.get(resource_id, "noreply@example.com"),
                    "last_updated": today.isoformat()
                }
                all_flat_records.append(flat_record)

        # --- Changes Start Here: Write to CSV instead of JSON ---
        if all_flat_records:
            # Get header from the first record's keys
            csv_headers = all_flat_records[0].keys()
            
            # Use an in-memory text buffer to write CSV
            output_buffer = io.StringIO()
            csv_writer = csv.DictWriter(output_buffer, fieldnames=csv_headers)
            
            csv_writer.writeheader()
            csv_writer.writerows(all_flat_records)
            
            csv_data = output_buffer.getvalue()
        else:
            logging.info("[ℹ️] No RI usage records found to write to CSV.")
            csv_data = "" # Write empty string if no records

        # Upload the aggregated CSV data to Azure Blob Storage
        blob_client = BlobClient.from_connection_string(
            conn_str=STORAGE_ACCOUNT_CONNECTION_STRING,
            container_name=RAW_USAGE_CONTAINER_NAME,
            blob_name=file_name
        )
        blob_client.upload_blob(csv_data, overwrite=True) # Upload CSV data
        logging.info(f"[⬆️] Successfully uploaded {file_name} to Blob container '{RAW_USAGE_CONTAINER_NAME}'.")

    except Exception as e:
        logging.error(f"[❌] An error occurred during query_ri_data_func execution: {e}")
        # Re-raise the exception to indicate function failure to Azure Monitor
        raise

    logging.info(f"Python timer trigger function finished at {datetime.utcnow().isoformat()}")