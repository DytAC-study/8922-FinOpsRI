import json
import os
import io
import base64
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import csv

# Azure Blob Storage imports for direct upload
from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.core.exceptions import ResourceExistsError

# Import email utility functions
from .email_utils import send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables (Read here as well for this script's context) ---
LOGICAPP_ENDPOINT = os.getenv("LOGICAPP_ENDPOINT")
EMAIL_RECIPIENTS = [r.strip() for r in os.getenv("EMAIL_RECIPIENTS", "").split(',') if r.strip()]
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "FinOps RI Report")


def generate_html_report(data: list, summary_date: str) -> str:
    """
    Generates a comprehensive HTML report from RI utilization analysis data.
    Includes sections for overall summary, expiring RIs, underutilized RIs, and unused RIs.
    """
    if not data:
        return f"<h1>FinOps RI Utilization Report - {summary_date}</h1><p>No data available for this report.</p>"

    df = pd.DataFrame(data)

    # Ensure date fields are in datetime objects for sorting, then format back to string for display
    for col in ['end_date', 'purchase_date']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d').fillna('N/A')

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FinOps RI Utilization Report - {summary_date}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; }}
            h1, h2 {{ color: #0056b3; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .alert-critical {{ color: #d9534f; font-weight: bold; }}
            .alert-warning {{ color: #f0ad4e; font-weight: bold; }}
            .summary-box {{ border: 1px solid #ccc; padding: 15px; margin-bottom: 20px; background-color: #f9f9f9; }}
            .status-healthy {{ color: green; font-weight: bold; }}
            .status-underutilized {{ color: orange; font-weight: bold; }}
            .status-unused {{ color: red; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>FinOps RI Utilization Report</h1>
        <p><strong>Report Date:</strong> {summary_date}</p>
        <p>This report provides an overview of your Azure Reserved Instance (RI) utilization.</p>
        <p>Analysis Period: {data[0].get('analysis_period_start', 'N/A')} to {data[0].get('analysis_period_end', 'N/A')}</p>
    """

    # --- Overall Summary ---
    total_ris = len(df)
    healthy_ris = df[df['status'] == 'healthy'].shape[0]
    underutilized_ris = df[df['status'] == 'underutilized'].shape[0]
    unused_ris = df[df['status'] == 'unused'].shape[0]
    expiring_ris = df[df['expiry_status'].isin(['expiring_soon', 'expired'])].shape[0]
    expired_ris = df[df['expiry_status'] == 'expired'].shape[0]
    no_data_ris = df[df['status'] == 'No Data'].shape[0]
    partial_data_ris = df[df['status'] == 'Partial Data'].shape[0]

    html_content += f"""
        <h2>Summary Overview</h2>
        <div class="summary-box">
            <p><strong>Total Reserved Instances:</strong> {total_ris}</p>
            <ul>
                <li>Healthy Utilization: <span class="status-healthy">{healthy_ris}</span></li>
                <li>Underutilized: <span class="status-underutilized">{underutilized_ris}</span></li>
                <li>Unused: <span class="status-unused">{unused_ris}</span></li>
                <li>Expiring Soon: <span class="alert-warning">{expiring_ris}</span></li>
                <li>Expired: <span class="alert-critical">{expired_ris}</span></li>
                <li>No Data / Partial Data: {no_data_ris + partial_data_ris}</li>
            </ul>
        </div>
    """

    # --- Expiring RIs ---
    expiring_df = df[df['expiry_status'].isin(['expiring_soon', 'expired'])].copy()
    expiring_df['end_date_sort'] = pd.to_datetime(expiring_df['end_date'], errors='coerce')
    expiring_df = expiring_df.sort_values(by='end_date_sort').drop(columns=['end_date_sort'])

    if not expiring_df.empty:
        html_content += "<h2>Reserved Instances Expiring Soon or Expired</h2>"
        # --- MODIFIED: Removed specific columns from HTML output ---
        html_content += expiring_df[[
            "ri_id", "subscription_id", "sku_name", "region", "end_date", "days_remaining", "expiry_status"
        ]].to_html(index=False)
    else:
        html_content += "<h2>Reserved Instances Expiring Soon or Expired</h2><p>No RIs found expiring soon or already expired within the analysis period.</p>"

    # --- Underutilized RIs ---
    underutilized_df = df[df['status'] == 'underutilized'].sort_values(by='utilization_percent_period')
    if not underutilized_df.empty:
        html_content += "<h2>Underutilized Reserved Instances</h2>"
        # --- MODIFIED: Removed specific columns from HTML output ---
        html_content += underutilized_df[[
            "ri_id", "subscription_id", "sku_name", "region", "utilization_percent_period"
        ]].to_html(index=False)
    else:
        html_content += "<h2>Underutilized Reserved Instances</h2><p>No significantly underutilized RIs found.</p>"

    # --- Unused RIs ---
    unused_df = df[df['status'] == 'unused'].sort_values(by='max_consecutive_unused_days', ascending=False)
    if not unused_df.empty:
        html_content += "<h2>Unused Reserved Instances</h2>"
        # --- MODIFIED: Removed specific columns from HTML output ---
        html_content += unused_df[[
            "ri_id", "subscription_id", "sku_name", "region", "utilization_percent_period"
        ]].to_html(index=False)
    else:
        html_content += "<h2>Unused Reserved Instances</h2><p>No unused RIs found.</p>"

    # --- All RIs (Detailed Table) ---
    if not df.empty:
        html_content += "<h2>Detailed Reserved Instance Report</h2>"
        # --- MODIFIED: Removed specific columns from HTML output ---
        html_content += df[[
            "ri_id", "subscription_id", "sku_name", "region", "purchase_date", "end_date",
            "term_months", "utilization_percent_period", "days_remaining", "expiry_status",
            "status"
        ]].to_html(index=False)

    html_content += """
        <p>Best regards,<br>Your FinOps Automation Team</p>
    </body>
    </html>
    """
    logger.info("HTML report generated successfully.")
    return html_content


def generate_csv_report(data: list) -> io.BytesIO:
    """
    Generates a CSV report from RI utilization analysis data.
    Returns a BytesIO object containing the CSV content.
    This function is now expected to receive data specific to a recipient.
    """
    if not data:
        logger.warning("No data to generate CSV report.")
        return io.BytesIO("".encode('utf-8'))

    df = pd.DataFrame(data)

    # Ensure date columns are formatted consistently for CSV
    for col in ['purchase_date', 'end_date', 'analysis_period_start', 'analysis_period_end']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')

    # --- MODIFIED: Adjust fieldnames for CSV - now it's for recipient-specific data ---
    # Removed 'email_recipient' from CSV as it's implicit for the recipient
    fieldnames = [
        "subscription_id",
        "ri_id",
        "sku_name",
        "region",
        "purchase_date",
        "term_months",
        "utilization_percent_period",
        "days_remaining",
        "end_date",
        "status",
        "expiry_status",
        "total_underutilized_days_period",
        "total_unused_days_period",
        "missing_days",
        "alert",
        "analysis_period_start",
        "analysis_period_end",
        "max_consecutive_underutilized_days",
        "max_consecutive_unused_days"
    ]
    
    csv_output = io.StringIO()
    writer = csv.DictWriter(csv_output, fieldnames=fieldnames, lineterminator='\n', restval='')
    writer.writeheader()

    for row in data:
        ordered_row = {field: row.get(field, '') for field in fieldnames}
        writer.writerow(ordered_row)

    bytes_buffer = io.BytesIO(csv_output.getvalue().encode('utf-8-sig'))
    bytes_buffer.seek(0)
    return bytes_buffer


def upload_blob_to_storage(filename: str, file_buffer: io.BytesIO, container_name: str, storage_conn_string: str):
    """
    Uploads a file (from a BytesIO buffer) to Azure Blob Storage.
    Uses the provided storage_conn_string.
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_conn_string)

        container_client = ContainerClient.from_connection_string(conn_str=storage_conn_string, container_name=container_name)
        try:
            container_client.create_container()
            logger.info(f"Container '{container_name}' created (if it didn't exist).")
        except ResourceExistsError: # Catch specific error for container already exists
            logger.warning(f"Container '{container_name}' already exists. Skipping creation.")
        except Exception as e:
            logger.error(f"Failed to ensure container '{container_name}' exists: {e}. Assuming it exists.")

        blob_client = container_client.get_blob_client(filename)
        blob_client.upload_blob(file_buffer.getvalue(), overwrite=True)
        logger.info(f"Successfully uploaded {filename} to container '{container_name}'.")
    except Exception as e:
        logger.error(f"Failed to upload {filename} to blob storage: {e}", exc_info=True)
        raise


def generate_and_send_reports(
    records: list,
    summary_date: str,
    storage_conn_string: str,
    email_reports_container: str,
    default_recipient: str
):
    """
    Groups RI utilization records by recipient, generates HTML and CSV reports,
    archives CSVs to blob storage, and sends email notifications.
    """
    if not records:
        logger.warning("No records provided for report generation. Skipping report generation and email send.")
        return

    # Group records by email recipient
    recipient_grouped_data = defaultdict(list)
    for record in records:
        recipient = record.get("email_recipient")
        if recipient and recipient != "N/A":
            for r in recipient.split(','): # Handle multiple recipients in one field
                recipient_grouped_data[r.strip()].append(record)
        else:
            # If no specific recipient, assign to default recipient
            if default_recipient:
                recipient_grouped_data[default_recipient].append(record)
            else:
                logger.warning(f"Record {record.get('ri_id')} has no specific recipient and no default recipient is set. Skipping email for this record.")

    if not recipient_grouped_data:
        logger.info("No recipients found with data or default recipient not set. No emails will be sent.")
        return

    # Initialize container_client outside the try-except to ensure it's in scope for upload_blob_to_storage
    container_client = None
    try:
        container_client = ContainerClient.from_connection_string(
            conn_str=storage_conn_string,
            container_name=email_reports_container
        )
        container_client.create_container() # This will now handle ResourceExistsError gracefully
        logger.info(f"Ensured blob container '{email_reports_container}' exists.")
    except Exception as e:
        logger.error(f"Failed to access or create blob container '{email_reports_container}': {e}", exc_info=True)
        pass # Allow email sending to proceed even if archiving fails


    # --- Iterate through recipients and send reports ---
    for recipient, data_for_recipient in recipient_grouped_data.items():
        logger.info(f"Preparing report for recipient: {recipient}")

        # Generate HTML report for current recipient's data
        html_content = generate_html_report(data_for_recipient, summary_date)
        
        # --- MODIFIED: Generate CSV report for each recipient's data ---
        recipient_csv_buffer = generate_csv_report(data_for_recipient)
        recipient_csv_filename = f"finops-ri-report-{summary_date}_{recipient.replace('@', '_at_').replace('.', '_')}.csv" # Unique filename per recipient

        # Upload recipient-specific CSV to Blob Storage
        if container_client:
            try:
                upload_blob_to_storage(recipient_csv_filename, recipient_csv_buffer, email_reports_container, storage_conn_string)
            except Exception as e:
                logger.error(f"Failed to upload recipient CSV report '{recipient_csv_filename}' to blob storage: {e}", exc_info=True)
        else:
            logger.warning(f"Skipping recipient CSV report upload for {recipient} due to previous container access failure.")

        # Reset buffer for base64 encoding for email attachment
        recipient_csv_buffer.seek(0)
        csv_b64 = base64.b64encode(recipient_csv_buffer.getvalue()).decode('utf-8')

        # Determine subject
        subject = f"{EMAIL_SUBJECT_PREFIX} - {summary_date} - RI Utilization"
        if recipient == default_recipient and len(recipient_grouped_data) > 1:
             subject += " (Consolidated)" # Indicate if default receives consolidated report

        # Send email with HTML body and recipient-specific CSV attachment
        send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_content,
            attachment_b64=csv_b64,
            attachment_filename=recipient_csv_filename # Attach recipient-specific CSV
        )
