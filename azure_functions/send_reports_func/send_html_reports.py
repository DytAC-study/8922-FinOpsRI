import os
import json
import csv
from datetime import datetime
from collections import defaultdict
from azure.storage.blob import BlobClient, ContainerClient
import io
import base64
from azure.core.exceptions import ResourceExistsError

from .email_utils import send_email

import logging
logger = logging.getLogger(__name__)

def generate_html_table(data, summary_date):
    """
    Generates an HTML table string from the provided RI utilization data.
    Adds color coding based on status and collects alerts for display outside the table.
    """
    
    # 1. Collect alerts separately for display outside the table
    alerts_html_section = ""
    for r in data:
        alert_msg = r.get("alert", "")
        if alert_msg:
            # Applying red color and bold directly in the <p> tag as per user's preference for alerts
            alerts_html_section += f"""
            <p style='color: #dc3545; font-weight: bold;'>
                <strong>Alert for {r.get("ri_id", "-")} ({r.get("region", "-")}):</strong> {alert_msg}
            </p>
            """

    # 2. Construct the HTML header part of the email body
    html_header = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>RI Utilization Report for {summary_date}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 14px; color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; font-weight: bold; }}
            /* Row specific background colors */
            .healthy {{ background-color: #d4edda; }} /* Light green */
            .underutilized {{ background-color: #fff3cd; }} /* Light orange */
            .unused {{ background-color: #f8d7da; }} /* Light red */
            .expired {{ background-color: #f8d7da; }} /* Light red */
            .expiring_soon {{ background-color: #fff3cd; }} /* Light orange */
        </style>
    </head>
    <body>
        <h2>Azure RI Utilization Summary - {summary_date}</h2>
        <p>This report provides an overview of your Azure Reserved Instance utilization.</p>
    """
    
    # 3. Insert alerts section if any alerts exist, before the main table
    if alerts_html_section:
        html_header += f"""
        <div style="margin-top: 15px; padding: 10px; border: 1px solid #dc3545; background-color: #f8d7da; border-radius: 5px;">
            <h3>Alerts Overview</h3>
            {alerts_html_section}
        </div>
        """

    # 4. Continue with the HTML table structure
    html_header += """
        <table>
            <thead>
                <tr>
                    <th>Subscription ID</th>
                    <th>RI ID</th>
                    <th>SKU Name</th>
                    <th>Region</th>
                    <th>Purchase Date</th>
                    <th>End Date</th>
                    <th>Term (Months)</th>
                    <th>Utilization (%)</th>
                    <th>Days Remaining</th>
                    <th>Status</th>
                    <th>Expiry Status</th>
                    <th>Email Recipient</th>
                    </tr>
            </thead>
            <tbody>
    """
    
    rows = ""
    for r in data:
        status = r.get("status", "unknown")
        utilization = r.get("utilization_percent", "-")
        days = r.get("days_remaining", "-")
        
        # Determine the class for row background color
        row_class = ""
        if "unused" in status or "expired" in status:
            row_class = "unused"
        elif "underutilized" in status or "expiring_soon" in status:
            row_class = "underutilized"
        elif "healthy" in status:
            row_class = "healthy"

        rows += f"""
        <tr class="{row_class}">
            <td>{r.get("subscription_id", "-")}</td>
            <td>{r.get("ri_id", "-")}</td>
            <td>{r.get("sku_name", "-")}</td>
            <td>{r.get("region", "-")}</td>
            <td>{r.get("purchase_date", "-")}</td>
            <td>{r.get("end_date", "-")}</td>
            <td>{r.get("term_months", "-")}</td>
            <td>{utilization}%</td>
            <td>{days}</td>
            <td>{status}</td>
            <td>{r.get("expiry_status", "-")}</td>
            <td>{r.get("email_recipient", "-")}</td>
        </tr>
        """
    
    html_footer = """
            </tbody>
        </table>
        <p style="margin-top: 20px; font-size: 12px; color: #777;">
            This report is automatically generated. Please do not reply directly.
        </p>
    </body>
    </html>
    """

    return html_header + rows + html_footer


def generate_and_send_reports(
    records, summary_date, storage_conn_string, email_reports_container,
    email_method, smtp_host, smtp_port, smtp_user, smtp_pass, smtp_sender,
    logicapp_endpoint, default_recipient
):
    """
    Generates HTML reports and CSV attachments based on RI utilization records,
    and sends them via email.
    """
    blob_service_client = BlobClient.from_connection_string(
        conn_str=storage_conn_string,
        container_name=email_reports_container,
        blob_name="temp" # dummy name
    )._get_container_client() # Get a container client

    # Ensure the email reports container exists
    try:
        blob_service_client.create_container()
        logger.info(f"Container '{email_reports_container}' created (if it didn't exist).")
    except ResourceExistsError:
        logger.warning(f"Container '{email_reports_container}' already exists. Skipping creation.")
    except Exception as e:
        logger.error(f"Failed to ensure container '{email_reports_container}' exists: {e}. Assuming it exists.")


    # Group records by email recipient
    reports_by_recipient = defaultdict(list)
    for record in records:
        recipient = record.get("email_recipient")
        if recipient:
            reports_by_recipient[recipient].append(record)
        else:
            # FIX: If email_recipient is missing, send to default_recipient if available
            if default_recipient:
                logger.warning(f"Record for RI {record.get('ri_id', 'N/A')} is missing email_recipient. Sending to default: {default_recipient}")
                reports_by_recipient[default_recipient].append(record)
            else:
                logger.warning(f"Record for RI {record.get('ri_id', 'N/A')} is missing email_recipient and no default_recipient is set. Skipping email for this record.")


    if not reports_by_recipient:
        logger.info("No recipients found for email reports. No emails will be sent.")
        return

    for recipient, data_for_recipient in reports_by_recipient.items():
        logger.info(f"Generating report for recipient: {recipient}")

        # Generate HTML content
        html_content = generate_html_table(data_for_recipient, summary_date)
        html_blob_name = f"ri_utilization_report_{summary_date.replace('-', '_')}_{recipient.replace('@', '_').replace('.', '_')}.html"
        
        # Save HTML to blob (optional, but good for archiving/debugging)
        try:
            html_blob_client = blob_service_client.get_blob_client(html_blob_name)
            html_blob_client.upload_blob(html_content.encode('utf-8'), overwrite=True)
            logger.info(f"[📥] Archived HTML report to blob: {html_blob_name}")
        except Exception as e:
            logger.error(f"[❌] Failed to archive HTML report '{html_blob_name}' to blob storage: {e}", exc_info=True)


        # Generate CSV content in-memory
        csv_output = io.StringIO()
        # Fieldnames ordered to align with HTML display for main columns, plus all other data fields
        fieldnames = [
            "subscription_id",
            "ri_id",
            "sku_name",
            "region",
            "purchase_date",
            "end_date",
            "term_months",
            "utilization_percent",
            "days_remaining",
            "status",
            "expiry_status",
            "email_recipient",
            "alert", # 'alert' is still a data field in CSV
            "underutilized_days",
            "unused_days",
            "missing_days",
            "report_date"
        ]

        csv_writer = csv.DictWriter(csv_output, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(data_for_recipient)
        
        # --- MODIFIED: Encode with UTF-8-SIG to include BOM ---
        # This is crucial for Excel/Gmail to correctly interpret UTF-8 CSVs directly
        csv_bytes = csv_output.getvalue().encode('utf-8-sig')

        csv_blob_name = f"ri_utilization_report_{summary_date.replace('-', '_')}_{recipient.replace('@', '_').replace('.', '_')}.csv"
        
        # Archive CSV to blob Storage
        try:
            csv_blob_client = blob_service_client.get_blob_client(csv_blob_name)
            csv_blob_client.upload_blob(csv_bytes, overwrite=True)
            logger.info(f"[📥] Archived CSV report to blob: {csv_blob_name}")
        except Exception as e:
            logger.error(f"[❌] Failed to archive CSV report '{csv_blob_name}' to blob storage: {e}", exc_info=True)


        # Convert csv_bytes to Base64 for email attachment
        csv_b64_content = base64.b64encode(csv_bytes).decode('utf-8')

        # Region-wise alert count for email subject
        region_alerts = defaultdict(int)
        for r in data_for_recipient:
            # Only count if there's an actual alert message for relevant statuses
            if r.get("status") in ("underutilized", "unused", "expired", "expiring_soon") and r.get("alert"):
                region_alerts[r.get("region", "unknown")] += 1
        total_alerts = sum(region_alerts.values())
        region_summary = ", ".join(f"{region}: {count}" for region, count in region_alerts.items())
        
        email_subject = f"Azure RI Utilization Summary for {summary_date}"
        if total_alerts > 0:
            email_subject += f" ({total_alerts} Alerts: {region_summary})"

        # Send email using the unified send_email function from email_utils
        send_email(
            recipient=recipient,
            subject=email_subject,
            html_body=html_content,
            attachment_b64=csv_b64_content,
            attachment_filename=csv_blob_name,
            email_method=email_method,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_pass=smtp_pass,
            smtp_sender=smtp_sender,
            logicapp_endpoint=logicapp_endpoint
        )
        logger.info(f"[📧] Sent RI utilization report to {recipient}")