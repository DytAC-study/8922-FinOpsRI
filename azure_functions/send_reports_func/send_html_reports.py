import os
import json
import csv
from datetime import datetime
from collections import defaultdict
from azure.storage.blob import BlobClient, ContainerClient, PublicAccess
import io
import base64
from azure.core.exceptions import ResourceExistsError

from .email_utils import send_email

import logging
logger = logging.getLogger(__name__)

def generate_html_table(data):
    """
    Generates an HTML table string from the provided RI utilization data.
    Adds alert summary at the top and color-coded rows based on status.
    """
    alerts_html = ""
    rows = ""

    for r in data:
        status = r.get("status", "unknown")
        utilization = r.get("utilization_percent", "-")
        days = r.get("days_remaining", "-")
        alert_msg = r.get("alert", "")
        purchase_date = r.get("purchase_date", "-")
        term_months = r.get("term_months", "-")
        expiry_status = r.get("expiry_status", "-")
        report_date = r.get("report_date", "-")

        # Build alert display above table
        if alert_msg:
            alerts_html += f"""
            <p style='color: #dc3545; font-weight: bold;'>
                <strong>Alert for {r.get("ri_id", "-")} ({r.get("region", "-")}):</strong> {alert_msg}
            </p>
            """

        # Determine row background color
        color = "#f8d7da" if "unused" in status else \
                "#fff3cd" if "underutilized" in status else \
                "#d4edda" if "healthy" in status else \
                "#f8d7da" if "expired" in status else \
                "#fff3cd"

        rows += f"""
        <tr style="background-color: {color};">
            <td>{r.get("subscription_id", "-")}</td>
            <td>{r.get("ri_id", "-")}</td>
            <td>{r.get("sku_name", "-")}</td>
            <td>{r.get("region", "-")}</td>
            <td>{purchase_date}</td>
            <td>{term_months}</td>
            <td>{utilization}%</td>
            <td>{days}</td>
            <td>{status}</td>
            <td>{expiry_status}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
    body {{ font-family: Arial, sans-serif; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
    </style>
    </head>
    <body>
    <h2>Azure RI Utilization Report</h2>
    <div style="margin-bottom: 20px;">
        <h3>Alerts Overview</h3>
        {alerts_html or "<p>No alerts found.</p>"}
    </div>
    <table>
        <thead>
            <tr>
                <th>Subscription ID</th>
                <th>RI ID</th>
                <th>SKU Name</th>
                <th>Region</th>
                <th>Purchase Date</th>
                <th>Term (Months)</th>
                <th>Utilization (%)</th>
                <th>Days Remaining</th>
                <th>Status</th>
                <th>Expiry Status</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <p>This report summarizes your Azure RI utilization as of {report_date}.</p>
    <p>For more details, please refer to the attached CSV report.</p>
    </body>
    </html>
    """
    return html_content

def generate_csv_report_content(data):
    """
    Generates CSV content as bytes from the provided RI utilization data.
    The 'alert' field is excluded from the CSV but still used in the HTML.
    """
    csv_output = io.StringIO()
    fieldnames = [
        "subscription_id",
        "ri_id",
        "sku_name",
        "region",
        "purchase_date",
        "term_months",
        "utilization_percent",
        "days_remaining",
        "end_date",
        "status",
        "expiry_status",
        "underutilized_days",
        "unused_days",
        "missing_days",
        "email_recipient",
        "report_date"
    ]
    writer = csv.DictWriter(csv_output, fieldnames=fieldnames, lineterminator='\n', restval='')
    writer.writeheader()

    # Exclude the 'alert' field from each row before writing
    for row in data:
        row = {k: v for k, v in row.items() if k in fieldnames}
        writer.writerow(row)

    return csv_output.getvalue().encode('utf-8-sig')


def generate_and_send_reports(
    records, summary_date, storage_conn_string, email_reports_container, default_recipient
):
    """
    Groups RI utilization records by recipient, generates HTML and CSV reports,
    archives CSVs to blob storage, and sends email notifications.
    """
    grouped_by_recipient = defaultdict(list)
    for record in records:
        recipient = record.get("email_recipient")
        if recipient:
            grouped_by_recipient[recipient].append(record)
        elif default_recipient:
            grouped_by_recipient[default_recipient].append(record)
        else:
            logger.warning(f"[⚠️] Record has no email_recipient and no default_recipient is set. Skipping record: {record.get('ri_id')}")

    if not grouped_by_recipient:
        logger.info("[ℹ️] No recipients found with data or default recipient not set. No emails will be sent.")
        return

    try:
        container_client = ContainerClient.from_connection_string(
            conn_str=storage_conn_string,
            container_name=email_reports_container
        )
        container_client.create_container()
        logger.info(f"[✅] Ensured blob container '{email_reports_container}' exists.")
    except ResourceExistsError:
        logger.info(f"[ℹ️] Blob container '{email_reports_container}' already exists.")
    except Exception as e:
        logger.error(f"[❌] Failed to access or create blob container '{email_reports_container}': {e}", exc_info=True)
        return

    for recipient, data_for_recipient in grouped_by_recipient.items():
        logger.info(f"[📧] Preparing report for recipient: {recipient}")

        html_content = generate_html_table(data_for_recipient)
        csv_bytes = generate_csv_report_content(data_for_recipient)

        safe_recipient_name = recipient.replace("@", "_at_").replace(".", "_")
        csv_blob_name = f"ri_utilization_report_{summary_date}_{safe_recipient_name}.csv"

        try:
            blob_client = container_client.get_blob_client(csv_blob_name)
            blob_client.upload_blob(csv_bytes, overwrite=True)
            logger.info(f"[📥] Archived CSV report to blob: {csv_blob_name}")
        except Exception as e:
            logger.error(f"[❌] Failed to archive CSV report '{csv_blob_name}' to blob storage: {e}", exc_info=True)
            continue

        csv_b64_content = base64.b64encode(csv_bytes).decode('utf-8')

        region_alerts = defaultdict(int)
        for r in data_for_recipient:
            if r.get("status") in ("underutilized", "unused"):
                region_alerts[r.get("region", "unknown")] += 1
        total_alerts = sum(region_alerts.values())
        region_summary = ", ".join(f"{region}: {count}" for region, count in region_alerts.items())

        email_subject = f"Azure RI Utilization Summary for {summary_date}"
        if total_alerts > 0:
            email_subject += f" ({total_alerts} Alerts: {region_summary})"

        send_email(
            recipient=recipient,
            subject=email_subject,
            html_body=html_content,
            attachment_b64=csv_b64_content,
            attachment_filename=csv_blob_name
        )
