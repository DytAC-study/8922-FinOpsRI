import logging
import json
import os
import psycopg2
import pandas as pd
import io
from datetime import datetime, timedelta
import azure.functions as func
import re

# Azure Blob Storage imports for direct upload
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

# Import the core analysis function
from .analyze_ri_utilization import analyze_ri_utilization_for_period

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BLOB_CONTAINER_ARCHIVED_REPORTS = os.environ.get('RI_ARCHIVED_REPORTS_CONTAINER', "ri-archived-reports")

MIN_UTIL_THRESHOLD = float(os.getenv("MIN_UTIL_THRESHOLD", "0.8"))
EXPIRY_WARN_DAYS = int(os.getenv("EXPIRY_WARN_DAYS", "90"))
MIN_UNDERUTILIZED_DAYS_FOR_ALERT = int(os.getenv("MIN_UNDERUTILIZED_DAYS_FOR_ALERT", "5"))
MIN_UNUSED_DAYS_FOR_ALERT = int(os.getenv("MIN_UNUSED_DAYS_FOR_ALERT", "3"))
ANALYSIS_PERIOD_DAYS = int(os.getenv("ANALYSIS_PERIOD_DAYS", "30"))
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "unknown")
DEFAULT_SKU = os.getenv("DEFAULT_SKU", "unknown")

# DATABASE_CONNECTION_STRING is used directly within analyze_ri_utilization.py
# So, it doesn't need to be passed as an argument to analyze_ri_utilization_for_period.


def generate_excel_report(data: list, output_buffer: io.BytesIO):
    """
    Generates an Excel report from the analysis data.
    """
    if not data:
        logger.warning("No data to generate Excel report.")
        df = pd.DataFrame(columns=[
            "RI ID", "Subscription ID", "SKU Name", "Region", "Purchase Date", "End Date",
            "Term Months", "Overall Utilization (%)", "Days Remaining", "Expiry Status",
            "Status", "Total Underutilized Days (Period)", "Total Unused Days (Period)",
            "Missing Days", "Email Recipient", "Alert Message",
            "Analysis Period Start", "Analysis Period End",
            "Max Consecutive Underutilized Days", "Max Consecutive Unused Days"
        ])
    else:
        column_mapping = {
            "ri_id": "RI ID",
            "subscription_id": "Subscription ID",
            "sku_name": "SKU Name",
            "region": "Region",
            "purchase_date": "Purchase Date",
            "end_date": "End Date",
            "term_months": "Term Months",
            "utilization_percent_period": "Overall Utilization (%)",
            "days_remaining": "Days Remaining",
            "expiry_status": "Expiry Status",
            "status": "Status",
            "total_underutilized_days_period": "Total Underutilized Days (Period)",
            "total_unused_days_period": "Total Unused Days (Period)",
            "missing_days": "Missing Days",
            "email_recipient": "Email Recipient",
            "alert": "Alert Message",
            "analysis_period_start": "Analysis Period Start",
            "analysis_period_end": "Analysis Period End",
            "max_consecutive_underutilized_days": "Max Consecutive Underutilized Days",
            "max_consecutive_unused_days": "Max Consecutive Unused Days"
        }
        df = pd.DataFrame(data).rename(columns=column_mapping)

        ordered_columns = [
            "RI ID", "Subscription ID", "SKU Name", "Region", "Purchase Date", "End Date",
            "Term Months", "Overall Utilization (%)", "Days Remaining", "Expiry Status",
            "Status", "Total Underutilized Days (Period)", "Total Unused Days (Period)",
            "Missing Days", "Max Consecutive Underutilized Days", "Max Consecutive Unused Days",
            "Alert Message", "Email Recipient", "Analysis Period Start", "Analysis Period End"
        ]
        df = df[ordered_columns]

    with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='RI Utilization Report', index=False)

        workbook = writer.book
        worksheet = writer.sheets['RI Utilization Report']

        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)
    logger.info("Excel report generated successfully.")


def upload_blob_to_storage(filename: str, file_buffer: io.BytesIO, container_name: str):
    """
    Uploads a file (from a BytesIO buffer) to Azure Blob Storage.
    """
    storage_conn_string = os.getenv("AzureWebJobsStorage")
    if not storage_conn_string:
        logger.error("AzureWebJobsStorage environment variable is not set. Cannot upload blob.")
        raise ValueError("Azure Storage connection string is missing.")

    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_conn_string)

        container_client = blob_service_client.get_container_client(container_name)
        try:
            container_client.create_container()
            logger.info(f"Container '{container_name}' created (if it didn't exist).")
        except ResourceExistsError:
            logger.warning(f"Container '{container_name}' already exists. Skipping creation.")
        except Exception as e:
            logger.warning(f"Failed to ensure container '{container_name}' exists: {e}. Assuming it exists.")

        blob_client = container_client.get_blob_client(filename)
        blob_client.upload_blob(file_buffer.getvalue(), overwrite=True)
        logger.info(f"Successfully uploaded {filename} to container '{container_name}'.")
    except Exception as e:
        logger.error(f"Failed to upload {filename} to blob storage: {e}")
        raise


def main(msg: func.QueueMessage):
    logger.info(f"Python queue trigger function processed message: {msg.get_body().decode('utf-8')}")

    try:
        message_data = json.loads(msg.get_body().decode('utf-8'))
        source_blob_name = message_data.get("blob_name", "unknown_source_blob")
        report_date_str = message_data.get("report_date")

        logger.info(f"Triggered by message from {source_blob_name} for report_date: {report_date_str}.")

        if not report_date_str:
            logger.warning(f"report_date not found in message. Attempting to parse from blob name '{source_blob_name}'.")
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', source_blob_name)
            if date_match:
                report_date_str = date_match.group(1)
                logger.info(f"Parsed report_date '{report_date_str}' from blob name.")
            else:
                report_date_str = datetime.now().strftime('%Y-%m-%d')
                logger.warning(f"Could not parse date from blob name '{source_blob_name}'. Using current date '{report_date_str}' for analysis.")

        analysis_period_end_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        analysis_period_start_date = analysis_period_end_date - timedelta(days=ANALYSIS_PERIOD_DAYS - 1)

        logger.info(f"Analyzing RI utilization for the period: {analysis_period_start_date.strftime('%Y-%m-%d')} to {analysis_period_end_date.strftime('%Y-%m-%d')}")

        # --- FIX: Removed db_conn_string from the arguments ---
        analysis_results = analyze_ri_utilization_for_period(
            analysis_period_start_date_str=analysis_period_start_date.strftime('%Y-%m-%d'),
            analysis_period_end_date_str=analysis_period_end_date.strftime('%Y-%m-%d'),
            min_util_threshold=MIN_UTIL_THRESHOLD,
            expiry_warn_days=EXPIRY_WARN_DAYS,
            min_underutilized_days_for_alert=MIN_UNDERUTILIZED_DAYS_FOR_ALERT,
            min_unused_days_for_alert=MIN_UNUSED_DAYS_FOR_ALERT,
            default_region=DEFAULT_REGION,
            default_sku=DEFAULT_SKU
        )

        if not analysis_results:
            logger.warning("No data found for RI analysis. Exiting as no email notification is configured.")
            return

        excel_output = io.BytesIO()
        excel_filename = f"finops-ri-report-{analysis_period_end_date.strftime('%Y-%m-%d')}_{ANALYSIS_PERIOD_DAYS}days.xlsx"
        generate_excel_report(analysis_results, excel_output)
        upload_blob_to_storage(excel_filename, excel_output, BLOB_CONTAINER_ARCHIVED_REPORTS)

        json_summary_filename = f"ri_utilization_summary_{analysis_period_end_date.strftime('%Y-%m-%d')}.json"
        json_content = json.dumps(analysis_results, indent=4)
        json_buffer = io.BytesIO(json_content.encode('utf-8'))
        upload_blob_to_storage(json_summary_filename, json_buffer, "ri-analysis-output")

        logger.info(f"RI analysis and report generation completed for period {analysis_period_start_date.strftime('%Y-%m-%d')} to {analysis_period_end_date.strftime('%Y-%m-%d')}.")

    except json.JSONDecodeError as jde:
        logger.error(f"Invalid JSON message: {jde}. Message: {msg.get_body().decode('utf-8')}")
        raise
    except ValueError as ve:
        logger.error(f"Configuration error: {ve}")
        raise
    except Exception as e:
        logger.error(f"An unhandled error occurred in analyze_ri_func: {e}", exc_info=True)
        raise
    finally:
        pass