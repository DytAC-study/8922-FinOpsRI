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

# 导入分析模块中的核心函数
from .analyze_ri_utilization import analyze_utilization_from_db

def main(msg: func.QueueMessage, outputBlob: func.Out[bytes]):
    logging.info(f"Python queue trigger function processed message: {msg.get_body().decode('utf-8')}")

    try:
        message_data = json.loads(msg.get_body().decode('utf-8'))
        source_blob_name = message_data.get("blob_name", "unknown_source_blob")
        logging.info(f"Triggered by message from {source_blob_name} data import.")

        logging.info("Starting RI utilization analysis...")

        conn_string = os.environ["DATABASE_CONNECTION_STRING"]

        # 从环境变量获取分析参数，如果未设置则使用默认值
        min_utilization_threshold = float(os.environ.get("MIN_UTILIZATION_THRESHOLD", "60.0"))
        expiry_warning_days = int(os.environ.get("EXPIRY_WARNING_DAYS", "30"))
        # 确保这些参数在您的 Function App 配置中也已设置，或者接受默认值
        analysis_window_days = int(os.environ.get("ANALYSIS_WINDOW_DAYS", "90"))
        underutilized_days_threshold = int(os.environ.get("UNDERUTILIZED_DAYS_THRESHOLD", "7"))
        unused_days_threshold = int(os.environ.get("UNUSED_DAYS_THRESHOLD", "15"))
        default_region = os.environ.get("DEFAULT_REGION", "unknown")
        default_sku = os.environ.get("DEFAULT_SKU", "unknown")

        # 调用 analyze_ri_utilization.py 中的 analyze_utilization_from_db 函数
        # 这个函数将负责连接数据库、查询 ri_usage 表并进行分析
        analyzed_results = analyze_utilization_from_db(
            db_conn_string=conn_string, # 将 conn_string 正确传递给 db_conn_string 参数
            min_util_threshold=min_utilization_threshold,
            expiry_warn_days=expiry_warning_days,
            analysis_win_days=analysis_window_days,
            underutilized_days_threshold=underutilized_days_threshold,
            unused_days_threshold=unused_days_threshold,
            default_region=default_region,
            default_sku=default_sku
        )

        # 将分析结果转换为 DataFrame 以便后续生成 Excel 报告
        df = pd.DataFrame(analyzed_results)

        report_bytes = None
        report_name = f"RI_Report_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"

        if not df.empty:
            output = io.BytesIO()
            writer = pd.ExcelWriter(output, engine='xlsxwriter')

            # 1. Overall Summary 概览
            summary_data = df.groupby(['status', 'expiry_status']).size().reset_index(name='count')
            summary_data.to_excel(writer, sheet_name='Summary', index=False)

            # 2. Detailed RI Report 详细报告
            detailed_report_cols = [
                'subscription_id', 'ri_id', 'sku_name', 'region', 'purchase_date',
                'term_months', 'utilization_percent', 'days_remaining',
                'status', 'expiry_status', 'underutilized_days', 'unused_days',
                'alert', 'email_recipient'
            ]
            df_detailed = df[detailed_report_cols]
            df_detailed.to_excel(writer, sheet_name='Detailed RI Report', index=False)

            # 3. Actionable Items - Underutilized 低利用率项
            df_underutilized = df[df['status'] == 'underutilized'].copy()
            df_underutilized.to_excel(writer, sheet_name='Underutilized RIs', index=False)

            # 4. Actionable Items - Unused 未使用项
            df_unused = df[df['status'] == 'unused'].copy()
            df_unused.to_excel(writer, sheet_name='Unused RIs', index=False)

            writer.close() # 必须关闭 writer 才能将内容保存到 BytesIO
            report_bytes = output.getvalue()
            outputBlob.set(report_bytes)
            logging.info(f"Successfully generated and uploaded RI utilization report: {report_name}")

            # 假设您还有发送邮件的逻辑，可以放在这里，使用 `df` 中的数据
            # 例如，从这里开始可以调用您的 email_utils 来发送报告邮件
            # logic_app_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
            # recipient_email = os.environ.get("RECIPIENT_EMAIL", "your_recipient_email@example.com")
            # ... (您的邮件发送逻辑) ...
            logic_app_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
            recipient_email = os.environ.get("RECIPIENT_EMAIL", "your_recipient_email@example.com")

            if logic_app_endpoint:
                try:
                    # 准备邮件内容，例如：
                    email_subject = f"FinOps RI Utilization Report - {datetime.now().strftime('%Y-%m-%d')}"
                    # 这是一个简单的示例，您可以根据需要生成更复杂的 HTML
                    html_body = f"""
                    <p>Dear Team,</p>
                    <p>Please find the attached RI Utilization Report.</p>
                    <p>Total records analyzed: {len(df)}</p>
                    <p>Unused RIs: {len(df_unused)}</p>
                    <p>Underutilized RIs: {len(df_underutilized)}</p>
                    <p>Best regards,<br>Your FinOps Automation Team</p>
                    """

                    # 您可能需要将 report_bytes 转换为 base64 编码以作为附件发送
                    attachment_b64 = base64.b64encode(report_bytes).decode('utf-8')
                    attachment_filename = report_name

                    requests.post(logic_app_endpoint, json={
                        "recipient": recipient_email,
                        "subject": email_subject,
                        "html": html_body,
                        "attachments": [{
                            "Name": attachment_filename,
                            "ContentBytes": attachment_b64
                        }]
                    })
                    logging.info("Sent email notification with RI report.")
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error sending report email via Logic App: {e}")
            else:
                logging.warning("LOGICAPP_ENDPOINT environment variable is not set. Skipping email send.")


        else:
            logging.warning("No data found for RI analysis. Skipping report generation and email send.")
            logic_app_endpoint = os.environ.get("LOGICAPP_ENDPOINT")
            recipient_email = os.environ.get("RECIPIENT_EMAIL", "your_recipient_email@example.com")

            if logic_app_endpoint:
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
            else:
                logging.warning("LOGICAPP_ENDPOINT environment variable is not set. Skipping no-data email notification.")


    except Exception as e:
        logging.error(f"An unhandled error occurred in analyze_ri_func: {e}")
        raise # 重新抛出异常，以便 Azure Functions 运行时捕获并处理