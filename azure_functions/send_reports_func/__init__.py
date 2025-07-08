import azure.functions as func
import logging
import os
import json
from datetime import datetime
from collections import defaultdict
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Import the reporting module from the same directory
from . import send_html_reports # Now it's a sibling module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
BLOB_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
# This container holds the JSON output from the analysis function
BLOB_CONTAINER_ANALYSIS_OUTPUT = "ri-analysis-output"
# This container will hold the generated HTML/CSV reports before emailing
BLOB_CONTAINER_EMAIL_REPORTS = "ri-email-reports" 

def main(mytimer: func.TimerRequest) -> None:
    utc_timestamp = datetime.utcnow().isoformat()
    logger.info(f'[⏰] Python timer trigger function processed a request at {utc_timestamp}')

    analysis_summary_date = datetime.now().strftime("%Y-%m-%d")
    latest_summary_blob_name = f"ri_utilization_summary_{analysis_summary_date}.json"

    records = []
    if not BLOB_STORAGE_ACCOUNT_NAME:
        logger.error("[❌] AZURE_STORAGE_ACCOUNT_NAME is not set. Cannot read analysis results from Blob.")
        return

    try:
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=f"https://{BLOB_STORAGE_ACCOUNT_NAME}.blob.core.windows.net", 
            credential=credential
        )
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_ANALYSIS_OUTPUT)
        blob_client = container_client.get_blob_client(latest_summary_blob_name)

        if blob_client.exists():
            blob_data = blob_client.download_blob().readall()
            records = json.loads(blob_data)
            logger.info(f"[📥] Successfully read analysis summary from Blob: {latest_summary_blob_name}")
        else:
            logger.warning(f"[⚠️] No analysis summary file found in '{BLOB_CONTAINER_ANALYSIS_OUTPUT}' container for today: {latest_summary_blob_name}. Skipping report generation.")
            # If no analysis file, send a general notification to the default recipient if configured
            logic_app_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
            recipient_email = os.environ.get("RECIPIENT_EMAIL") # Use a general recipient for no-data alert

            if logic_app_endpoint and recipient_email:
                try:
                    no_data_subject = f"FinOps RI Report - No Data Available - {analysis_summary_date}"
                    no_data_html_body = "<p>Dear Team,</p><p>The FinOps RI analysis was scheduled, but no analysis data was found in the database/blob for today.</p><p>Best regards,<br>Your FinOps Automation Team</p>"
                    # Here you could potentially call send_html_reports.email_utils.send_email
                    # or a dedicated function within send_html_reports for no-data notifications
                    pass 
                except Exception as e:
                    logger.error(f"Error sending no-data notification email: {e}")
            return # Exit if no records

    except Exception as e:
        logger.error(f"[❌] Error loading latest summary from Blob '{latest_summary_blob_name}': {e}")
        raise # Re-raise for Function App to log

    if not records:
        logger.info("[⚠️] No records found for reporting after loading analysis. Exiting.")
        return

    # Gather email sending configuration from environment variables
    email_method = os.environ.get("EMAIL_METHOD", "logicapp") # e.g., 'logicapp' or 'smtp'
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_sender = os.environ.get("SMTP_SENDER", "noreply@example.com")
    logicapp_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
    
    # Call the central report generation and sending function
    # Use os.environ["AzureWebJobsStorage"] for the storage connection string
    # This is a standard environment variable provided by Azure Functions.
    send_html_reports.generate_and_send_reports(
        records=records,
        summary_date=analysis_summary_date,
        storage_conn_string=os.environ["AzureWebJobsStorage"], 
        email_reports_container=BLOB_CONTAINER_EMAIL_REPORTS,
        email_method=email_method,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        smtp_sender=smtp_sender,
        logicapp_endpoint=logicapp_endpoint
    )

    logger.info(f"[✅] Report Sending Function completed successfully.")