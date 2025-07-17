import azure.functions as func
import logging
import os
import json
from datetime import datetime
from collections import defaultdict

from . import send_html_reports

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
BLOB_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")

BLOB_CONTAINER_ANALYSIS_OUTPUT = "ri-analysis-output"
BLOB_CONTAINER_EMAIL_REPORTS = "ri-email-reports"

# --- MODIFIED: Removed 'name' from function signature ---
def main(inputblob: func.InputStream) -> None:
    """
    Azure Function entry point triggered by a new or updated blob in 'ri-analysis-output' container.
    This function reads the RI utilization summary JSON, generates HTML/CSV reports, and sends emails.
    """
    logger.info(f"[⏰] Python Blob trigger function processed blob: {inputblob.name}")

    try:
        # Read the blob content
        records = json.loads(inputblob.read().decode('utf-8'))
        logger.info(f"[✅] Successfully loaded {len(records)} records from Blob '{inputblob.name}'.")

        # Extract summary date from blob name
        blob_name_parts = inputblob.name.split('/')
        file_name = blob_name_parts[-1]
        
        # Expect file_name in format like 'ri_utilization_summary_YYYY-MM-DD.json'
        # Extract date from the file name
        try:
            analysis_summary_date_str = file_name.replace("ri_utilization_summary_", "").replace(".json", "")
            analysis_summary_date = datetime.strptime(analysis_summary_date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
            logger.info(f"Extracted summary date: {analysis_summary_date}")
        except ValueError:
            logger.error(f"[❌] Could not parse summary date from blob name: {file_name}. Using current date as fallback.")
            analysis_summary_date = datetime.now().strftime("%Y-%m-%d")

        # --- REMOVED: SMTP and EMAIL_METHOD related environment variable retrievals ---
        # email_method, smtp_host, smtp_port, smtp_user, smtp_pass, smtp_sender, logicapp_endpoint
        # 这些参数现在都由 email_utils.py 内部处理或不再需要

        # --- FIX for Issue 4: Get general recipient for fallback ---
        default_recipient = os.environ.get("RECIPIENT_EMAIL")
        if not default_recipient:
            logger.error("[❌] RECIPIENT_EMAIL environment variable is not set. Some reports might not be sent to a default recipient.")

        # Call the central report generation and sending function
        # 使用 os.environ["AzureWebJobsStorage"] 获取存储连接字符串
        # 这是一个 Azure Functions 提供的标准环境变量。
        send_html_reports.generate_and_send_reports(
            records=records,
            summary_date=analysis_summary_date,
            storage_conn_string=os.environ["AzureWebJobsStorage"],
            email_reports_container=BLOB_CONTAINER_EMAIL_REPORTS,
            # 移除不再需要的参数
            default_recipient=default_recipient
        )
        logger.info(f"[✅] Executed 'Functions.send_reports_func' successfully for {inputblob.name}")

    except Exception as e:
        logger.error(f"[❌] Executed 'Functions.send_reports_func' (Failed, Id={os.environ.get('WEBSITE_INSTANCE_ID')}, Error='{e}')", exc_info=True)
        raise # Re-raise the exception for the Azure Functions runtime to capture and log