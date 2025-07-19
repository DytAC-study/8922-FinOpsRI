import logging
import os
import json
import csv
from datetime import datetime, timedelta
import azure.functions as func
from azure.storage.blob import BlobClient
import io

# Import the core logic from the adjacent file
from .query_azure_ri_data import fetch_subscriptions, fetch_tagged_emails, fetch_usage_details

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Blob Storage Configuration (from Function App Settings)
STORAGE_ACCOUNT_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
RAW_USAGE_CONTAINER_NAME = "ri-usage-raw" # Container to store raw RI usage data CSVs

def main(mytimer: func.TimerRequest):
    """
    Azure Function entry point for querying RI data.
    Triggered by a timer (e.g., daily).
    This function now fetches daily granular data and stores it.
    """
    utc_timestamp = datetime.utcnow().isoformat()
    logger.info(f'Python timer trigger function started at {utc_timestamp}')

    # --- MODIFIED: Target date is yesterday for daily fetch ---
    target_date = datetime.utcnow().date() - timedelta(days=1) 
    file_name = f"azure_ri_usage_daily_summary_{target_date.isoformat()}.csv" # Changed filename to reflect daily data

    all_daily_records = []

    try:
        subscriptions = fetch_subscriptions()
        logger.info(f"[🔎] Found {len(subscriptions)} subscription(s).")

        for sub_id in subscriptions:
            logger.info(f"[📦] Processing subscription: {sub_id} for date {target_date.isoformat()}")
            
            # --- MODIFIED: Fetch daily usage details for the target_date ---
            daily_usage_for_sub = fetch_usage_details(sub_id, target_date)
            
            # --- MODIFIED: Enrich with email tags and append to all_daily_records ---
            # Fetch email tags once per subscription if needed, or if tags are per RI, fetch per RI
            # Assuming email_tags are per resource_id and don't change daily
            email_tags = fetch_tagged_emails(sub_id) 

            for record in daily_usage_for_sub:
                # Add email recipient from tags, default if not found
                record["email_recipient"] = email_tags.get(record["resource_id"].lower(), "noreply@example.com")
                all_daily_records.append(record)

        if all_daily_records:
            # Get header from the first record's keys
            csv_headers = all_daily_records[0].keys()
            
            output_buffer = io.StringIO()
            csv_writer = csv.DictWriter(output_buffer, fieldnames=csv_headers)
            
            csv_writer.writeheader()
            csv_writer.writerows(all_daily_records)
            
            csv_data = output_buffer.getvalue()
        else:
            logger.info("[ℹ️] No RI daily usage records found for the target date to write to CSV.")
            csv_data = ""

        blob_client = BlobClient.from_connection_string(
            conn_str=STORAGE_ACCOUNT_CONNECTION_STRING,
            container_name=RAW_USAGE_CONTAINER_NAME,
            blob_name=file_name
        )
        blob_client.upload_blob(csv_data, overwrite=True)
        logger.info(f"[⬆️] Successfully uploaded {file_name} to Blob container '{RAW_USAGE_CONTAINER_NAME}'.")

    except Exception as e:
        logger.error(f"[❌] An error occurred during query_ri_data_func execution: {e}", exc_info=True)
        raise

    logger.info(f"Python timer trigger function finished at {datetime.utcnow().isoformat()}")
