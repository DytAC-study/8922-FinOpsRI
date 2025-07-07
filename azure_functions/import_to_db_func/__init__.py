import logging
import os
import json
import psycopg2
import csv
import io
from datetime import datetime, timedelta
import azure.functions as func

def main(inputBlob: func.InputStream, outputQueue: func.Out[str]):
    logging.info(f"Python blob trigger function processed blob\n"
                 f"Name: {inputBlob.name}\n"
                 f"Size: {inputBlob.length} Bytes")

    try:
        conn_string = os.environ["DATABASE_CONNECTION_STRING"]

        blob_content = inputBlob.read().decode('utf-8')
        csv_reader = csv.reader(io.StringIO(blob_content))

        # 读取CSV头部，用于后续按名称获取列数据
        header = next(csv_reader)
        logging.info(f"CSV Header: {header}")

        # 创建头部到索引的映射，提高代码健壮性
        header_map = {col.strip(): i for i, col in enumerate(header)}

        # 定义插入语句，匹配 ri_usage 表的实际列名和顺序
        # 参照 import_to_db.py 中的 ri_usage 表定义
        insert_query = """
        INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (subscription_id, resource_id, usage_start) DO NOTHING; -- 添加 ON CONFLICT 处理重复数据
        """

        with psycopg2.connect(conn_string) as conn:
            with conn.cursor() as cur:
                rows_processed = 0
                # 从第二行开始处理数据（第一行是头部）
                for row_num, row in enumerate(csv_reader):
                    # 检查行是否有足够的列以避免 IndexError
                    # 我们需要至少 'email_recipient' 这一列，它是第7列（索引为6）
                    # 考虑到 header_map 的最大索引是 7 (email_recipient的索引是7，但它的长度是8)
                    # 理论上应该检查 len(row) >= max(header_map.values()) + 1
                    # 这里简化为直接检查需要的列是否存在
                    required_columns = ['subscription_id', 'ri_id', 'utilization_percent', 'purchase_date', 'email_recipient']
                    if not all(col in header_map for col in required_columns):
                        logging.error(f"CSV Header missing one or more required columns. Expected: {required_columns}. Actual: {header}")
                        # 如果头部缺失关键列，则停止处理或跳过所有行
                        break # 或者 continue 外层循环

                    if len(row) < len(header): # 确保当前行至少有头部那么多列
                         logging.warning(f"Skipping malformed row {row_num + 2} (not enough columns matching header): {row}")
                         continue

                    try:
                        # 根据头部映射从行中提取数据
                        subscription_id = row[header_map['subscription_id']].strip()
                        ri_id = row[header_map['ri_id']].strip()
                        utilization_percent = float(row[header_map['utilization_percent']].strip())
                        purchase_date_str = row[header_map['purchase_date']].strip()
                        email_recipient = row[header_map['email_recipient']].strip()

                        # 将 purchase_date 字符串转换为 ISO 格式的字符串，以匹配 ri_usage 表的 usage_start 字段 (TEXT 类型)
                        purchase_date_iso = datetime.strptime(purchase_date_str, '%Y-%m-%d').isoformat()

                        # 执行插入操作，传入正确顺序和类型的数据
                        cur.execute(insert_query, (
                            subscription_id,
                            ri_id,
                            utilization_percent,
                            purchase_date_iso,
                            email_recipient
                        ))
                        # 检查是否有行被实际插入（如果 rowcount 为 0，表示因 ON CONFLICT 而跳过）
                        if cur.rowcount > 0:
                            rows_processed += 1

                    except ValueError as ve:
                        logging.error(f"Data type conversion error for row {row_num + 2} ({row}): {ve}")
                        continue
                    except KeyError as ke:
                        # 如果 CSV 行的某个索引在 header_map 中找不到对应的键，理论上不应该发生如果前置检查通过
                        logging.error(f"Missing expected column index for key: {ke} in row {row_num + 2} ({row})")
                        continue
                    except Exception as e:
                        logging.error(f"Unexpected error processing row {row_num + 2} ({row}): {e}")
                        continue

                conn.commit() # 批量提交所有插入操作
                logging.info(f"Successfully imported {rows_processed} rows from {inputBlob.name} to PostgreSQL.")

        message = json.dumps({"blob_name": inputBlob.name, "status": "data_imported", "timestamp": datetime.now().isoformat()})
        outputQueue.set(message)
        logging.info(f"Sent message to analysis queue: {message}")

    except Exception as e:
        logging.error(f"Error in import_to_db_func processing {inputBlob.name}: {e}")
        raise