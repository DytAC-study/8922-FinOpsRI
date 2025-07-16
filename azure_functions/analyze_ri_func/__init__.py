import logging
import json
import os
import psycopg2 
import pandas as pd
import io 
from datetime import datetime, timedelta
import requests
import azure.functions as func
import re 

# Azure Blob Storage imports for direct upload
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
# Import ResourceExistsError for specific exception handling
from azure.core.exceptions import ResourceExistsError

# Import the core analysis function
from .analyze_ri_utilization import analyze_utilization_from_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- New: Define a separate container for archived Excel reports ---
BLOB_CONTAINER_ARCHIVED_REPORTS = "ri-archived-reports" # 或者您希望的任何其他合适名称
# ------------------------------------------------------------------

# Main function for the Queue Trigger
def main(msg: func.QueueMessage): 
    logger.info(f"Python queue trigger function processed message: {msg.get_body().decode('utf-8')}")

    conn = None 
    try:
        message_data = json.loads(msg.get_body().decode('utf-8'))
        source_blob_name = message_data.get("blob_name", "unknown_source_blob")
        logger.info(f"Triggered by message from {source_blob_name} data import.")

        # ==== Parse report_date from source_blob_name ====
        report_date_for_analysis = None
        date_match_for_analysis = re.search(r'(\d{4}-\d{2}-\d{2})', source_blob_name)
        if date_match_for_analysis:
            try:
                report_date_for_analysis = datetime.strptime(date_match_for_analysis.group(1), '%Y-%m-%d').strftime('%Y-%m-%d')
                logger.info(f"Parsed report_date '{report_date_for_analysis}' for analysis from blob name.")
            except ValueError:
                logger.warning(f"Could not parse date from blob name '{source_blob_name}'. Using current date for analysis.")
                report_date_for_analysis = datetime.now().strftime('%Y-%m-%d')
        else:
            logger.warning(f"No date found in blob name '{source_blob_name}'. Using current date for analysis.")
            report_date_for_analysis = datetime.now().strftime('%Y-%m-%d')

        # Retrieve environment variables for database connection and analysis thresholds
        conn_string = os.environ.get("DATABASE_CONNECTION_STRING")
        if not conn_string:
            logger.error("DATABASE_CONNECTION_STRING environment variable is not set. Cannot connect to database.")
            raise ValueError("Database connection string is missing.")

        min_util_threshold = int(os.environ.get("MIN_UTILIZATION_THRESHOLD", "60"))
        expiry_warn_days = int(os.environ.get("EXPIRY_WARNING_DAYS", "30"))
        analysis_win_days = int(os.environ.get("ANALYSIS_WINDOW_DAYS", "7"))
        underutilized_days_threshold = int(os.environ.get("UNDERUTILIZED_DAYS_THRESHOLD", "3"))
        unused_days_threshold = int(os.environ.get("UNUSED_DAYS_THRESHOLD", "3"))
        default_region = os.environ.get("DEFAULT_REGION", "eastus")
        default_sku = os.environ.get("DEFAULT_SKU", "Standard_DS1_v2")

        logger.info("Starting RI utilization analysis...")
        results = analyze_utilization_from_db(
            conn_string, min_util_threshold, expiry_warn_days, analysis_win_days,
            underutilized_days_threshold, unused_days_threshold, default_region, default_sku,
            report_date_for_analysis
        )

        if not results:
            logger.warning("No data found for RI analysis. Skipping report generation and email send.")
            logic_app_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
            
            # --- FIX for Issue 4: Ensure RECIPIENT_EMAIL is always from environment ---
            recipient_email = os.environ.get("RECIPIENT_EMAIL") 
            if not recipient_email:
                logger.error("RECIPIENT_EMAIL environment variable is not set. Cannot send no-data notification.")
                return # Cannot send email, return

            if logic_app_endpoint:
                try:
                    no_data_subject = f"FinOps RI Report - No Data Available - {datetime.now().strftime('%Y-%m-%d')}"
                    no_data_html_body = "<p>Dear Team,</p><p>The FinOps RI analysis was run, but no relevant data was found in the database to generate a report.</p><p>Best regards,<br>Your FinOps Automation Team</p>"

                    requests.post(logic_app_endpoint, json={
                        "recipient": recipient_email,
                        "subject": no_data_subject,
                        "html": no_data_html_body
                    })
                    logger.info("Sent email notification: No data for RI analysis.")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending no-data notification email: {e}.")
            else:
                logger.warning("LOGICAPP_ENDPOINT environment variable is not set. Skipping no-data email notification.")
            return # Exit if no results to process

        # --- Generate and Upload JSON Summary to ri-analysis-output ---
        json_summary_filename = f"ri_utilization_summary_{report_date_for_analysis}.json"
        
        storage_account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
        if not storage_account_name:
            logger.error("AZURE_STORAGE_ACCOUNT_NAME is not set. Cannot upload JSON summary.")
            raise ValueError("Azure Storage Account Name is missing.")

        try:
            credential = DefaultAzureCredential()
            blob_service_client = BlobServiceClient(account_url=f"https://{storage_account_name}.blob.core.windows.net", credential=credential)
            
            # Container for JSON summaries
            analysis_output_container_client = blob_service_client.get_container_client("ri-analysis-output")
            try:
                analysis_output_container_client.create_container()
                logger.info(f"Container 'ri-analysis-output' created (if it didn't exist).")
            except ResourceExistsError: # Catch specific error if container already exists
                logger.warning(f"Container 'ri-analysis-output' already exists. Skipping creation.")
            except Exception as e: 
                logger.warning(f"Failed to ensure container 'ri-analysis-output' exists: {e}. Assuming it exists.")

            json_blob_client = analysis_output_container_client.get_blob_client(json_summary_filename)
            
            json_content = json.dumps(results, indent=4) 
            json_blob_client.upload_blob(json_content.encode('utf-8'), overwrite=True)
            logger.info(f"Successfully uploaded JSON summary to blob: {json_summary_filename}")

        except Exception as e:
            logger.error(f"Failed to upload JSON summary {json_summary_filename} to blob storage: {e}")
            raise 

        # --- Generate and Upload Proper XLSX Report to a DIFFERENT container ---
        df = pd.DataFrame(results)

        excel_filename = f"finops-ri-report-{report_date_for_analysis}.xlsx"

        excel_output = io.BytesIO()

        with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='RI Utilization Report', index=False)

            workbook = writer.book
            worksheet = writer.sheets['RI Utilization Report']
            for i, col in enumerate(df.columns):
                max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2 
                worksheet.set_column(i, i, max_len)
            
        try:
            # --- MODIFIED: Handle container creation without exists_ok ---
            xlsx_archive_container_client = blob_service_client.get_container_client(BLOB_CONTAINER_ARCHIVED_REPORTS)
            try:
                xlsx_archive_container_client.create_container()
                logger.info(f"Container '{BLOB_CONTAINER_ARCHIVED_REPORTS}' created (if it didn't exist).")
            except ResourceExistsError: # Catch specific error if container already exists
                logger.warning(f"Container '{BLOB_CONTAINER_ARCHIVED_REPORTS}' already exists. Skipping creation.")
            except Exception as e: 
                logger.warning(f"Failed to ensure container '{BLOB_CONTAINER_ARCHIVED_REPORTS}' exists: {e}. Assuming it exists.")

            xlsx_blob_client = xlsx_archive_container_client.get_blob_client(excel_filename)
            # ----------------------------------------------------------

            xlsx_blob_client.upload_blob(excel_output.getvalue(), overwrite=True)
            logger.info(f"Successfully uploaded XLSX report to blob: {excel_filename} in container '{BLOB_CONTAINER_ARCHIVED_REPORTS}'")

        except Exception as e:
            logger.error(f"Failed to upload XLSX report {excel_filename} to blob storage: {e}")
            raise 

        logger.info(f"RI analysis and report generation completed for {report_date_for_analysis}.")

    except Exception as e:
        logger.error(f"An unhandled error occurred in analyze_ri_func: {e}")
        raise 

    finally:
        if conn:
            conn.close()
            logger.info("PostgreSQL connection closed.")