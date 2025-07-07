# email_utils.py – Unified email sender for Logic App and SMTP

import os
import smtplib
import base64
import json
from email.message import EmailMessage
from email.utils import formataddr
# Removed dotenv load_dotenv as it's not needed in Azure Functions (uses App Settings directly)
import requests

from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")  # smtp or logicapp

# SMTP config
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) # Default to 587 for TLS
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_SENDER = os.getenv("SMTP_SENDER", "no-reply@example.com")

# Logic App endpoint
LOGICAPP_ENDPOINT = os.getenv("LOGICAPP_ENDPOINT")

# Azure Blob Storage for attachments
BLOB_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
# Assuming reports are saved in ri-email-reports container
BLOB_CONTAINER_REPORTS = "ri-email-reports" 

def get_blob_content_as_base64(blob_name, container_name=BLOB_CONTAINER_REPORTS):
    """
    Reads a blob's content and returns it as a Base64 encoded string.
    """
    if not BLOB_STORAGE_ACCOUNT_NAME:
        logger.error("[❌] AZURE_STORAGE_ACCOUNT_NAME is not set in environment variables.")
        return None

    try:
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=f"https://{BLOB_STORAGE_ACCOUNT_NAME}.blob.core.windows.net", 
            credential=credential
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, 
            blob=blob_name
        )
        
        # Check if blob exists before downloading
        if not blob_client.exists():
            logger.warning(f"[⚠️] Blob '{blob_name}' not found in container '{container_name}'. Cannot attach.")
            return None

        blob_data = blob_client.download_blob().readall()
        logger.info(f"[📥] Successfully read blob: {blob_name}")
        return base64.b64encode(blob_data).decode("utf-8")
    except Exception as e:
        logger.error(f"[❌] Error reading blob '{blob_name}' from '{container_name}': {e}")
        return None

def send_email(recipient, subject, html_body, blob_attachment_name=None):
    """
    Sends an email using either SMTP or Logic App.
    attachment_name should be the full blob path (e.g., 'user_at_email_com_2023-01-01.csv')
    """
    attachment_b64 = None
    attachment_filename = None

    if blob_attachment_name:
        attachment_b64 = get_blob_content_as_base64(blob_attachment_name)
        if attachment_b64:
            attachment_filename = os.path.basename(blob_attachment_name)
            logger.info(f"[📎] Prepared attachment from Blob: {attachment_filename}")

    if EMAIL_METHOD == "smtp":
        send_via_smtp(recipient, subject, html_body, attachment_b64, attachment_filename)
    elif EMAIL_METHOD == "logicapp":
        send_via_logicapp(recipient, subject, html_body, attachment_b64, attachment_filename)
    else:
        logger.error(f"[❌] Unknown EMAIL_METHOD: {EMAIL_METHOD}")


def send_via_smtp(recipient, subject, html_body, attachment_b64=None, attachment_filename=None):
    """
    Sends an email via SMTP.
    """
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("FinOps Report", SMTP_SENDER))
        msg["To"] = recipient
        msg.set_content("This is an HTML email.")
        msg.add_alternative(html_body, subtype="html")

        if attachment_b64 and attachment_filename:
            # Decode base64 to bytes before attaching
            content = base64.b64decode(attachment_b64)
            # Assuming CSV, adjust subtype if needed for .html or other types
            maintype = 'text'
            subtype = 'csv'
            if attachment_filename.lower().endswith('.html'):
                subtype = 'html'
            elif attachment_filename.lower().endswith('.pdf'):
                maintype = 'application'
                subtype = 'pdf' # Or other binary type as needed
            
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=attachment_filename)
            logger.info(f"[📎] Attached via SMTP: {attachment_filename}")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USER and SMTP_PASS:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        logger.info(f"[📧] Email sent to {recipient} via SMTP")

    except Exception as e:
        logger.error(f"[❌] SMTP error: {e}")


def send_via_logicapp(recipient, subject, html_body, attachment_b64=None, attachment_filename=None):
    """
    Sends an email via Azure Logic App HTTP trigger.
    """
    try:
        if not LOGICAPP_ENDPOINT:
            logger.error("[❌] LOGICAPP_ENDPOINT is not set in environment variables.")
            return

        attachments = []
        if attachment_b64 and attachment_filename:
            attachments = [{
                "Name": attachment_filename,
                "ContentBytes": attachment_b64
            }]
            logger.info(f"[📎] Prepared attachment for Logic App: {attachment_filename}")

        payload = {
            "recipient": recipient,
            "subject": subject,
            "html": html_body,
            "attachments": attachments
        }

        headers = {"Content-Type": "application/json"}
        resp = requests.post(LOGICAPP_ENDPOINT, json=payload, headers=headers)

        if resp.status_code >= 200 and resp.status_code < 300:
            logger.info(f"[📧] Logic App email sent to {recipient}")
        else:
            logger.error(f"[❌] Logic App error: {resp.status_code} – {resp.text}")

    except Exception as e:
        logger.error(f"[❌] Logic App exception: {e}")