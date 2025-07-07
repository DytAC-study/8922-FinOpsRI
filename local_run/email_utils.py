# email_utils.py – Unified email sender for Logic App and SMTP

import os
import smtplib
import base64
import json
from email.message import EmailMessage
from email.utils import formataddr
from dotenv import load_dotenv
import requests

# Load .env variables
load_dotenv()

EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")  # smtp or logicapp

# SMTP config
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 25))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_SENDER = os.getenv("SMTP_SENDER", "no-reply@example.com")

# Logic App endpoint
LOGICAPP_ENDPOINT = os.getenv("LOGICAPP_ENDPOINT")


def send_email(recipient, subject, html_body, attachment=None):
    if EMAIL_METHOD == "smtp":
        send_via_smtp(recipient, subject, html_body, attachment)
    elif EMAIL_METHOD == "logicapp":
        send_via_logicapp(recipient, subject, html_body, attachment)
    else:
        print(f"[❌] Unknown EMAIL_METHOD: {EMAIL_METHOD}")


def send_via_smtp(recipient, subject, html_body, attachment=None):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("FinOps Report", SMTP_SENDER))
        msg["To"] = recipient
        msg.set_content("This is an HTML email.")
        msg.add_alternative(html_body, subtype="html")

        if attachment and os.path.isfile(attachment):
            with open(attachment, "rb") as f:
                content = f.read()
            filename = os.path.basename(attachment)
            msg.add_attachment(content, maintype="text", subtype="csv", filename=filename)
            print(f"[📎] Attached CSV: {attachment}")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USER and SMTP_PASS:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        print(f"[📧] Email sent to {recipient}")

    except Exception as e:
        print(f"[❌] SMTP error: {e}")


def send_via_logicapp(recipient, subject, html_body, attachment=None):
    try:
        attachments = []
        if attachment and os.path.isfile(attachment):
            with open(attachment, "rb") as f:
                b64content = base64.b64encode(f.read()).decode("utf-8")
            attachments = [{
                "Name": os.path.basename(attachment),
                "ContentBytes": b64content
            }]
            print(f"[📎] Prepared attachment: {attachments[0]['Name']}")

        payload = {
            "recipient": recipient,
            "subject": subject,
            "html": html_body,
            "attachments": attachments
        }

        headers = {"Content-Type": "application/json"}
        resp = requests.post(LOGICAPP_ENDPOINT, json=payload, headers=headers)

        if resp.status_code >= 200 and resp.status_code < 300:
            print(f"[📧] Logic App email sent to {recipient}")
        else:
            print(f"[❌] Logic App error: {resp.status_code} – {resp.text}")

    except Exception as e:
        print(f"[❌] Logic App exception: {e}")
