import os
import json
import csv
from datetime import datetime
from collections import defaultdict
from azure.storage.blob import BlobClient, ContainerClient

# Removed: from dotenv import load_dotenv (Azure Functions handle environment variables)
# Removed: from pathlib import Path (using blob storage for I/O)
# Import email utility functions from the same directory
from .email_utils import send_email

def generate_html_table(data):
    """
    Generates an HTML table string from the provided RI utilization data.
    Adds color coding based on status.
    """
    rows = ""
    for r in data:
        status = r.get("status", "unknown")
        utilization = r.get("utilization_percent", "-")
        days = r.get("days_remaining", "-")
        alert_msg = r.get("alert", "")

        color = "#f8d7da" if "unused" in status else \
                "#fff3cd" if "underutilized" in status else \
                "#d4edda" if "healthy" in status else \
                "#f8d7da" if "expired" in status else \
                "#fff3cd" # expiring_soon: light orange

        alert_html = f"<br><small style='color: #dc3545;'>{alert_msg}</small>" if alert_msg else ""

        rows += f"""
        <tr style="background-color: {color};">
            <td>{r.get("subscription_id", "-")}</td>
            <td>{r.get("ri_id", "-")}</td>
            <td>{r.get("sku_name", "-")}</td>
            <td>{r.get("region", "-")}</td>
            <td>{utilization}%</td>
            <td>{days}</td>
            <td>{status.capitalize()}</td>
            <td>{r.get("expiry_status", "-").replace('_', ' ').capitalize()}</td>
            <td>{alert_html}</td>
        </tr>
        """

    html_content = f"""
    <html>
    <head>
        <style>
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h2>Azure RI Utilization Summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Subscription ID</th>
                    <th>RI ID</th>
                    <th>SKU Name</th>
                    <th>Region</th>
                    <th>Utilization (%)</th>
                    <th>Days Remaining</th>
                    <th>Status</th>
                    <th>Expiry Status</th>
                    <th>Alerts</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html_content

def export_csv(data, filename):
    """
    Exports the given data to a CSV file.
    """
    if not data:
        return

    keys = data[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)

def generate_and_send_reports(
    records, summary_date, storage_conn_string, email_reports_container,
    email_method, smtp_host, smtp_port, smtp_user, smtp_pass, smtp_sender, logicapp_endpoint
):
    """
    Generates HTML and CSV reports based on analysis records, uploads them to blob storage,
    and sends email notifications.
    """
    grouped_by_recipient = defaultdict(list)
    for rec in records:
        email = rec.get("email_recipient")
        if email:
            grouped_by_recipient[email].append(rec)

    if not grouped_by_recipient:
        print("[⚠️] No email recipients found in the analysis data. No reports to send.")
        return

    # Create a Blob Container Client for reports if it doesn't exist
    container_client = ContainerClient.from_connection_string(
        conn_str=storage_conn_string,
        container_name=email_reports_container
    )
    try:
        container_client.create_container()
        print(f"[✅] Blob container '{email_reports_container}' ensured to exist.")
    except Exception as e:
        if "ContainerAlreadyExists" in str(e):
            print(f"[ℹ️] Blob container '{email_reports_container}' already exists.")
        else:
            print(f"[❌] Error creating blob container '{email_reports_container}': {e}")
            raise # Re-raise if container couldn't be created

    for recipient, data_for_recipient in grouped_by_recipient.items():
        safe_name = recipient.replace("@", "_at_").replace(".", "_")
        html_blob_name = f"{safe_name}_{summary_date}.html"
        csv_blob_name = f"{safe_name}_{summary_date}.csv"

        # Generate HTML content
        html_content = generate_html_table(data_for_recipient)

        # Upload HTML to Blob Storage
        html_blob_client = BlobClient.from_connection_string(
            conn_str=storage_conn_string,
            container_name=email_reports_container,
            blob_name=html_blob_name
        )
        html_blob_client.upload_blob(html_content, overwrite=True)
        print(f"📧 HTML report uploaded to blob: {html_blob_name}")

        # Generate CSV content (as a string to upload)
        csv_output = []
        if data_for_recipient:
            keys = data_for_recipient[0].keys()
            csv_output.append(",".join(keys)) # Header
            for row in data_for_recipient:
                csv_output.append(",".join(str(row.get(k, "")) for k in keys))
        csv_content = "\n".join(csv_output)

        # Upload CSV to Blob Storage
        csv_blob_client = BlobClient.from_connection_string(
            conn_str=storage_conn_string,
            container_name=email_reports_container,
            blob_name=csv_blob_name
        )
        csv_blob_client.upload_blob(csv_content, overwrite=True)
        print(f"📧 CSV report uploaded to blob: {csv_blob_name}")

        # Prepare for email sending - you'll need a way to get the blob content as bytes
        # For sending, we will temporarily download and then pass to email_utils.
        # In a real Azure Function, you might stream directly or pass Blob URLs if email service supports it.
        # For simplicity, let's download the generated CSV for attachment.
        csv_download_stream = csv_blob_client.download_blob()
        csv_bytes = csv_download_stream.readall()
        csv_attachment_info = {
            "name": csv_blob_name,
            "content": csv_bytes
        }

        # Region-wise alert count for email subject
        region_alerts = defaultdict(int)
        for r in data_for_recipient:
            if r.get("status") in ("underutilized", "unused"):
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
            attachment=csv_attachment_info, # Pass content and name
            email_method=email_method,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_pass=smtp_pass,
            smtp_sender=smtp_sender,
            logicapp_endpoint=logicapp_endpoint
        )
        print(f"[📧] Email sent to {recipient}")