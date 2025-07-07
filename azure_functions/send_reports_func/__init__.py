import azure.functions as func
import logging
import os
import json
from datetime import datetime
from collections import defaultdict
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Assuming email_utils.py is in a shared_modules folder sibling to send_reports_func
# Adjust import path if your shared_modules folder is elsewhere
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'shared_modules')))
from email_utils import send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
BLOB_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
BLOB_CONTAINER_OUTPUT = "ri-analysis-output"
BLOB_CONTAINER_REPORTS = "ri-email-reports" # Where HTML/CSV reports are saved

# --- HTML/CSV Generation Functions ---
def generate_html_table(data):
    """Generates an HTML table for the email body."""
    rows = ""
    # Define table headers
    rows += "<tr>"
    rows += "<th>Subscription ID</th>"
    rows += "<th>RI ID</th>"
    rows += "<th>SKU Name</th>"
    rows += "<th>Region</th>"
    rows += "<th>Utilization (%)</th>"
    rows += "<th>Days Remaining</th>"
    rows += "<th>Status</th>"
    rows += "<th>Expiry Status</th>"
    rows += "<th>Alert</th>"
    rows += "</tr>"

    for r in data:
        status = r.get("status", "unknown")
        utilization = r.get("utilization_percent", "-")
        days = r.get("days_remaining", "-")
        alert = r.get("alert", "")

        color = "#d4edda"  # healthy: light green
        if status == "unused":
            color = "#f8d7da"  # unused: light red
        elif status == "underutilized":
            color = "#fff3cd"  # underutilized: light yellow

        rows += f"""
        <tr style="background-color: {color};">
            <td>{r.get("subscription_id", "-")}</td>
            <td>{r.get("ri_id", "-")}</td>
            <td>{r.get("sku_name", "-")}</td>
            <td>{r.get("region", "-")}</td>
            <td>{utilization}</td>
            <td>{days}</td>
            <td>{status.capitalize()}</td>
            <td>{r.get("expiry_status", "-").replace('_', ' ').capitalize()}</td>
            <td>{alert}</td>
        </tr>
        """

    return f"""
    <table border="1" style="width:100%; border-collapse: collapse;">
        {rows}
    </table>
    """

def export_csv_to_blob(data, blob_name):
    """Exports data to a CSV and uploads it to Azure Blob Storage."""
    if not BLOB_STORAGE_ACCOUNT_NAME:
        logger.error("[❌] AZURE_STORAGE_ACCOUNT_NAME is not set. Cannot upload CSV to Blob Storage.")
        return None

    try:
        csv_content = "Subscription ID,RI ID,SKU Name,Region,Utilization (%),Days Remaining,Status,Expiry Status,Alert\n"
        for r in data:
            row = [
                str(r.get("subscription_id", "")),
                str(r.get("ri_id", "")),
                str(r.get("sku_name", "")),
                str(r.get("region", "")),
                str(r.get("utilization_percent", "")),
                str(r.get("days_remaining", "")),
                str(r.get("status", "")),
                str(r.get("expiry_status", "")),
                str(r.get("alert", ""))
            ]
            csv_content += ",".join(row) + "\n"

        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=f"https://{BLOB_STORAGE_ACCOUNT_NAME}.blob.core.windows.net", 
            credential=credential
        )
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_REPORTS)
        blob_client = container_client.get_blob_client(blob_name)
        
        blob_client.upload_blob(csv_content, overwrite=True)
        logger.info(f"[✅] CSV report generated and uploaded to Blob: {blob_name}")
        return blob_name # Return the blob name for attachment reference

    except Exception as e:
        logger.error(f"[❌] Error exporting CSV to Blob '{blob_name}': {e}")
        return None

def upload_html_to_blob(html_content, blob_name):
    """Uploads HTML content to Azure Blob Storage."""
    if not BLOB_STORAGE_ACCOUNT_NAME:
        logger.error("[❌] AZURE_STORAGE_ACCOUNT_NAME is not set. Cannot upload HTML to Blob Storage.")
        return None

    try:
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=f"https://{BLOB_STORAGE_ACCOUNT_NAME}.blob.core.windows.net", 
            credential=credential
        )
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_REPORTS)
        blob_client = container_client.get_blob_client(blob_name)
        
        blob_client.upload_blob(html_content, overwrite=True, content_settings={"ContentType": "text/html"})
        logger.info(f"[✅] HTML report uploaded to Blob: {blob_name}")
        return blob_name
    except Exception as e:
        logger.error(f"[❌] Error uploading HTML to Blob '{blob_name}': {e}")
        return None

# --- Azure Function Entry Point ---
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
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_OUTPUT)
        blob_client = container_client.get_blob_client(latest_summary_blob_name)

        if blob_client.exists():
            blob_data = blob_client.download_blob().readall()
            records = json.loads(blob_data)
            logger.info(f"[📥] Successfully read analysis summary from Blob: {latest_summary_blob_name}")
        else:
            logger.warning(f"[⚠️] No analysis summary file found in '{BLOB_CONTAINER_OUTPUT}' container for today: {latest_summary_blob_name}. Skipping report generation.")
            return

    except Exception as e:
        logger.error(f"[❌] Error loading latest summary from Blob '{latest_summary_blob_name}': {e}")
        raise # Re-raise for Function App to log

    if not records:
        logger.info("[⚠️] No records found for reporting. Exiting.")
        return

    # Group records by email recipient
    grouped = defaultdict(list)
    for rec in records:
        email = rec.get("email_recipient")
        if email:
            grouped.setdefault(email, []).append(rec)

    if not grouped:
        logger.warning("[⚠️] No recipients found in analysis data. No emails will be sent.")
        return

    # Process and send reports for each recipient
    for recipient, data in grouped.items():
        safe_name = recipient.replace("@", "_at_").replace(".", "_")
        html_blob_name = f"{safe_name}_{analysis_summary_date}.html"
        csv_blob_name = f"{safe_name}_{analysis_summary_date}.csv"

        html_content = generate_html_table(data)
        uploaded_html_blob_name = upload_html_to_blob(html_content, html_blob_name)

        uploaded_csv_blob_name = export_csv_to_blob(data, csv_blob_name)

        logger.info(f"[📊] Reports prepared for {recipient}. HTML: {uploaded_html_blob_name}, CSV: {uploaded_csv_blob_name}")

        # Region-wise alert count for email subject/body
        region_alerts = defaultdict(int)
        for r in data:
            if r.get("status") in ("underutilized", "unused"):
                region_alerts[r.get("region", "unknown")] += 1
        
        total_alerts = sum(region_alerts.values())
        region_summary = ", ".join(f"{region}: {count}" for region, count in region_alerts.items()) if region_alerts else "No specific region alerts"

        email_subject = f"🔔 FinOps RI Utilization Report - {analysis_summary_date} ({total_alerts} Alert{'s' if total_alerts != 1 else ''})"
        
        email_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h2 {{ color: #333; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .alert-message {{ color: #dc3545; font-weight: bold; }}
                .summary {{ margin-top: 20px; padding: 10px; background-color: #f0f0f0; border-left: 5px solid #007bff; }}
                .footer {{ margin-top: 30px; font-size: 0.9em; color: #777; }}
            </style>
        </head>
        <body>
            <h2>Azure RI Utilization Summary - {analysis_summary_date}</h2>
            <div class="summary">
                <p><strong>Overview:</strong> Total {len(data)} RI records analyzed for your subscriptions.</p>
                <p><strong>Alerts by Region:</strong> {region_summary}.</p>
                <p>Please find the detailed utilization report below and in the attached CSV.</p>
            </div>
            {html_content}
            <div class="footer">
                <p>This is an automated report from your FinOps RI Reporting System.</p>
                <p>Please do not reply to this email.</p>
            </div>
        </body>
        </html>
        """

        send_email(
            recipient=recipient,
            subject=email_subject,
            html_body=email_body,
            blob_attachment_name=uploaded_csv_blob_name # Attach the CSV from Blob Storage
        )

    logger.info(f"[✅] Report Sending Function completed successfully.")