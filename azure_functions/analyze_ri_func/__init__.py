import logging
import json
import os
import psycopg2
import pandas as pd
import io
import xlsxwriter 
from datetime import datetime, timedelta 
import base64 
import requests 
import azure.functions as func

def main(msg: func.QueueMessage, outputBlob: func.Out[bytes]):
    logging.info(f"Python queue trigger function processed message: {msg.get_body().decode('utf-8')}")

    try:
        message_data = json.loads(msg.get_body().decode('utf-8'))
        source_blob_name = message_data.get("blob_name", "unknown_source_blob")
        logging.info(f"Triggered by message from {source_blob_name} data import.")

        logging.info("Starting RI utilization analysis...")
        
        conn_string = os.environ["DATABASE_CONNECTION_STRING"]
        
        query = "SELECT * FROM ri_finops_data ORDER BY end_date ASC;" 
        
        df = pd.DataFrame()
        with psycopg2.connect(conn_string) as conn:
            df = pd.read_sql_query(query, conn)
        
        report_bytes = None 
        report_name = f"RI_Report_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx" 

        if not df.empty:
            min_utilization_threshold = float(os.environ.get("MIN_UTILIZATION_THRESHOLD", "60.0"))
            expiry_warning_days = int(os.environ.get("EXPIRY_WARNING_DAYS", "30"))

            df['utilization_percentage'] = pd.to_numeric(df['utilization_percentage'], errors='coerce')
            underutilized_ris = df[df['utilization_percentage'] < min_utilization_threshold].dropna(subset=['utilization_percentage'])
            
            df['end_date'] = pd.to_datetime(df['end_date']).dt.date
            expired_soon_ris = df[df['end_date'] <= (datetime.now() + timedelta(days=expiry_warning_days)).date()]
            
            output_buffer = io.BytesIO()
            workbook = xlsxwriter.Workbook(output_buffer, {'in_memory': True})
            worksheet = workbook.add_worksheet('RI Analysis Report')
            
            bold_format = workbook.add_format({'bold': True})
            header_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
            data_format = workbook.add_format({'border': 1})
            date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
            percentage_format = workbook.add_format({'num_format': '0.00%', 'border': 1})
            currency_format = workbook.add_format({'num_format': '$#,##0.00', 'border': 1})

            worksheet.set_column('A:G', 18) 
            
            worksheet.merge_range('A1:G1', 'FinOps Reserved Instance Utilization Report', bold_format)
            worksheet.write('A2', f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", bold_format)
            
            current_row = 4
            
            worksheet.write(current_row, 0, f'Underutilized RIs (Utilization < {min_utilization_threshold:.0f}%):', bold_format)
            current_row += 1
            
            if not underutilized_ris.empty:
                for col_num, value in enumerate(underutilized_ris.columns):
                    worksheet.write(current_row, col_num, value, header_format)
                current_row += 1

                for row_num, row_data in enumerate(underutilized_ris.values):
                    for col_num, value in enumerate(row_data):
                        cell_format = data_format 
                        if isinstance(value, datetime) or isinstance(value, datetime.date):
                            worksheet.write(current_row + row_num, col_num, value.strftime('%Y-%m-%d'))
                        else:
                            worksheet.write(current_row + row_num, col_num, str(value))
                current_row += len(underutilized_ris) + 2 
            else:
                worksheet.write(current_row, 0, 'No underutilized RIs found.', bold_format)
                current_row += 2


            worksheet.write(current_row, 0, f'RIs Expiring Soon (within {expiry_warning_days} days):', bold_format)
            current_row += 1

            if not expired_soon_ris.empty:
                for col_num, value in enumerate(expired_soon_ris.columns):
                    worksheet.write(current_row, col_num, value, header_format)
                current_row += 1

                for row_num, row_data in enumerate(expired_soon_ris.values):
                    for col_num, value in enumerate(row_data):
                        cell_format = data_format 
                        if isinstance(value, datetime) or isinstance(value, datetime.date):
                            worksheet.write(current_row + row_num, col_num, value.strftime('%Y-%m-%d'))
                        else:
                            worksheet.write(current_row + row_num, col_num, str(value))
                current_row += len(expired_soon_ris) + 2
            else:
                worksheet.write(current_row, 0, 'No RIs expiring soon found.', bold_format)
                current_row += 2


            workbook.close()
            
            report_bytes = output_buffer.getvalue() 
            
            outputBlob.set(report_bytes)
            logging.info(f"Generated and saved RI analysis report: {report_name} to Blob Storage (container: ri-analysis-output).")

            logic_app_endpoint = os.environ["LOGICAPP_ENDPOINT"]
            recipient_email = os.environ.get("RECIPIENT_EMAIL", "your_recipient_email@example.com") 
            
            subject = f"FinOps RI Utilization Report - {datetime.now().strftime('%Y-%m-%d')}"
            html_body = f"""
            <h1>FinOps RI Utilization Report</h1>
            <p>Dear Team,</p>
            <p>Please find the attached FinOps RI Utilization Report for your review, generated from data imported from <strong>{source_blob_name}</strong>.</p>
            <p>This report highlights underutilized Reserved Instances and those expiring soon, based on the latest analysis.</p>
            <p>Best regards,<br>Your FinOps Automation Team</p>
            """
            
            if report_bytes: 
                encoded_attachment = base64.b64encode(report_bytes).decode('utf-8')
                
                payload = {
                    "recipient": recipient_email,
                    "subject": subject,
                    "html": html_body,
                    "attachments": [
                        {
                            "ContentBytes": encoded_attachment,
                            "Name": report_name,
                            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        }
                    ]
                }
                
                try:
                    response = requests.post(logic_app_endpoint, json=payload)
                    response.raise_for_status() 
                    logging.info(f"Report email sent successfully via Logic App. Status: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error sending email via Logic App: {e}. Response: {response.text if response else 'N/A'}")
                except Exception as e:
                    logging.error(f"An unexpected error occurred while preparing/sending email: {e}")
            else:
                logging.warning("No report content generated, skipping email send with attachment.")
                try:
                    no_data_subject = f"FinOps RI Report - No Data Available - {datetime.now().strftime('%Y-%m-%d')}"
                    no_data_html_body = "<p>Dear Team,</p><p>The FinOps RI analysis was run, but no relevant data was found to generate a report.</p><p>Best regards,<br>Your FinOps Automation Team</p>"
                    requests.post(logic_app_endpoint, json={
                        "recipient": recipient_email, 
                        "subject": no_data_subject, 
                        "html": no_data_html_body
                    })
                    logging.info("Sent email notification: No data for RI analysis.")
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error sending no-data notification email: {e}. Response: {response.text if response else 'N/A'}")


        else:
            logging.warning("No data found for RI analysis. Skipping report generation and email send.")
            logic_app_endpoint = os.environ["LOGICAPP_ENDPOINT"]
            recipient_email = os.environ.get("RECIPIENT_EMAIL", "your_recipient_email@example.com")
            
            try:
                no_data_subject = f"FinOps RI Report - No Data Available - {datetime.now().strftime('%Y-%m-%d')}"
                no_data_html_body = "<p>Dear Team,</p><p>The FinOps RI analysis was run, but no relevant data was found in the database to generate a report.</p><p>Best regards,<br>Your FinOps Automation Team</p>"
                
                requests.post(logic_app_endpoint, json={
                    "recipient": recipient_email, 
                    "subject": no_data_subject, 
                    "html": no_data_html_body
                })
                logging.info("Sent email notification: No data for RI analysis.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Error sending no-data notification email: {e}. Response: {response.text if response else 'N/A'}")

    except Exception as e:
        logging.error(f"An unhandled error occurred in analyze_ri_func: {e}")
        raise