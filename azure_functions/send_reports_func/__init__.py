import azure.functions as func
import logging
import os
import json
from datetime import datetime
from collections import defaultdict
# DefaultAzureCredential and BlobServiceClient are no longer needed here for READING the input blob
# as the blob trigger provides the input stream directly.
# However, they are still needed in send_html_reports.py and email_utils.py for writing/reading other blobs.

# Import the reporting module from the same directory
from . import send_html_reports

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
# BLOB_STORAGE_ACCOUNT_NAME is still needed in send_html_reports.py and email_utils.py
# for archiving CSVs and fetching attachments.
BLOB_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")

# This container holds the JSON output from the analysis function
# This is now the container that the blobTrigger listens to
BLOB_CONTAINER_ANALYSIS_OUTPUT = "ri-analysis-output"

# This container will hold the generated HTML/CSV reports before emailing
BLOB_CONTAINER_EMAIL_REPORTS = "ri-email-reports"

def main(inputblob: func.InputStream) -> None:
    """
    Azure Function entry point triggered by a new or updated blob in 'ri-analysis-output' container.
    This function reads the RI utilization summary JSON, generates HTML/CSV reports, and sends emails.
    """
    blob_full_path = inputblob.name
    blob_name_only = os.path.basename(blob_full_path)

    logger.info(f'[⏰] Python Blob trigger function processed blob: {blob_full_path}')

    analysis_summary_date = ""
    records = []

    try:
        blob_content = inputblob.read().decode('utf-8')
        records = json.loads(blob_content)
        logger.info(f"[✅] Successfully loaded {len(records)} records from Blob '{blob_full_path}'.")

        if blob_name_only.startswith("ri_utilization_summary_") and blob_name_only.endswith(".json"):
            analysis_summary_date = blob_name_only.replace("ri_utilization_summary_", "").replace(".json", "")
            logger.info(f"Extracted summary date: {analysis_summary_date}")
        else:
            logger.warning(f"Blob name '{blob_name_only}' does not match expected format for date extraction. Using current date.")
            analysis_summary_date = datetime.now().strftime("%Y-%m-%d")

    except Exception as e:
        logger.error(f"[❌] Error processing blob '{blob_full_path}': {e}", exc_info=True)
        return

    # --- MODIFIED: Removed SMTP related environment variable retrievals ---
    # email_method is no longer needed as we hardcode to Logic App in email_utils.py
    # smtp_host, smtp_port, smtp_user, smtp_pass, smtp_sender are removed.
    logicapp_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
    
    # --- Get general recipient for fallback ---
    default_recipient = os.environ.get("RECIPIENT_EMAIL")
    if not default_recipient:
        logger.error("[❌] RECIPIENT_EMAIL environment variable is not set. Some reports might not be sent to a default recipient.")

    # Call the central report generation and sending function
    # Use os.environ["AzureWebJobsStorage"] for the storage connection string
    # This is a standard environment variable provided by Azure Functions.
    send_html_reports.generate_and_send_reports(
        records=records,
        summary_date=analysis_summary_date,
        storage_conn_string=os.environ["AzureWebJobsStorage"], 
        email_reports_container=BLOB_CONTAINER_EMAIL_REPORTS,
        # --- MODIFIED: Only pass Logic App specific parameters ---
        logicapp_endpoint=logicapp_endpoint,
        default_recipient=default_recipient
    )
    logger.info(f"[✅] Python Blob trigger function completed for blob: {blob_full_path}")