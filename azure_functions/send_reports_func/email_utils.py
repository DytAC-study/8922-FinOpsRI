# email_utils.py – Unified email sender for Logic App

import os
import base64
import json
import requests

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Logic App endpoint (REQUIRED)
LOGICAPP_ENDPOINT = os.getenv("LOGICAPP_ENDPOINT")

# --- REMOVED: All SMTP related functions and variables ---
# No send_via_smtp function
# No SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_SENDER environment variable usage

def send_via_logicapp(recipient, subject, html_body, attachment_b64=None, attachment_filename=None):
    """
    Sends an email via Azure Logic App HTTP trigger.
    """
    try:
        if not LOGICAPP_ENDPOINT:
            logger.error("[❌] LOGICAPP_ENDPOINT is not set in environment variables. Email cannot be sent via Logic App.")
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
            # Modified: Added exc_info=True for detailed traceback on Logic App errors
            logger.error(f"[❌] Logic App returned status code {resp.status_code} for recipient {recipient}: {resp.text}", exc_info=True)

    except Exception as e:
        # Modified: Added exc_info=True for detailed traceback on general Logic App sending failures
        logger.error(f"[❌] Logic App error sending email to {recipient}: {e}", exc_info=True)


# --- MODIFIED: Main send_email function now directly calls send_via_logicapp ---
def send_email(recipient, subject, html_body, attachment=None, attachment_b64=None, attachment_filename=None):
    """
    Sends an email using Logic App (hardcoded).
    """
    # Removed the EMAIL_METHOD check, always use Logic App
    send_via_logicapp(recipient, subject, html_body, attachment_b64, attachment_filename)