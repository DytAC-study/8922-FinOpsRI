import logging
import os
import json
import psycopg2
import csv
import io
import re
from datetime import datetime, timedelta
import azure.functions as func

# ===================================================
# 从 import_to_db.py 整合过来的函数
# ---------------------------------------------------

def _parse_db_connection_string(conn_string):
    """Parses a PostgreSQL connection string into a dictionary of parameters."""
    db_params = {}
    parts = conn_string.strip().split(';')
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            db_params[key.strip()] = value.strip()
    return db_params

def create_table(db_conn_string):
    """
    Creates the 'ri_usage' table in the PostgreSQL database if it does not already exist.
    This table stores the flattened Reserved Instance usage data.
    """
    conn = None
    try:
        db_params = _parse_db_connection_string(db_conn_string)
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ri_usage (
            subscription_id TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            usage_quantity REAL,
            usage_start TEXT NOT NULL,
            email_recipient TEXT,
            report_date TEXT NOT NULL,
            sku_name TEXT,
            region TEXT,
            term_months INTEGER,
            PRIMARY KEY (subscription_id, resource_id, report_date)
        );
        """)
        conn.commit()
        cursor.close()
        logging.info("Table 'ri_usage' created or already exists.") # 更改为 logging
    except Exception as e:
        logging.error(f"Error creating table: {e}") # 更改为 logging
        raise # Re-raise to propagate the error
    finally:
        if conn:
            conn.close()

def import_json_data_to_db(db_conn_string, data, date_str, source_filename=""):
    """
    Imports a list of flat JSON records (representing RI usage) into the PostgreSQL database.
    Uses ON CONFLICT DO NOTHING to handle potential duplicate entries based on the primary key.
    """
    conn = None
    inserted = 0
    skipped = 0
    # The usage_start for each record will be derived from the blob's date_str
    # Note: This function's INSERT statement (and schema) needs to match the new `ri_usage` table.
    # The current `main` function directly uses the CSV, so this `import_json_data_to_db`
    # might not be used directly, but updated for completeness.
    usage_start_iso = f"{date_str}T00:00:00Z" # Assuming 'date_str' is YYYY-MM-DD

    try:
        db_params = _parse_db_connection_string(db_conn_string)
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()

        for entry in data:
            try:
                # This INSERT statement here is simplified. In your main function, you're getting more fields.
                # If this function is still intended for use, ensure `entry` contains all required fields
                # and this query matches the target table schema including sku_name, region, term_months, report_date
                # For this example, I'm assuming 'data' here is a list of dictionaries with specific keys
                # that match the older schema of this function.
                # If this function is only a placeholder and not actively used, its exact content is less critical.
                cursor.execute("""
                INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient, report_date, sku_name, region, term_months)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (subscription_id, resource_id, report_date) DO NOTHING;
                """, (
                    entry.get("subscription_id"),
                    entry.get("ri_id"),
                    entry.get("utilization_percent"),
                    usage_start_iso, # Using the parsed date string for usage_start
                    entry.get("email_recipient"),
                    date_str, # Assuming date_str is the report_date for these records
                    entry.get("sku_name", "N/A"), # Assuming these fields are in the JSON data too if this is used
                    entry.get("region", "N/A"),
                    entry.get("term_months", 0)
                ))
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as inner_e:
                logging.error(f"Error inserting entry {entry.get('ri_id')} for {date_str}: {inner_e}")
                # Log the error but continue processing other entries if possible

        conn.commit()
        logging.info(f"[📥] {source_filename} – Inserted: {inserted}, Skipped (already exist): {skipped}")
    except Exception as e:
        logging.error(f"Error importing data for {source_filename}: {e}")
        raise
    finally:
        if conn:
            conn.close()

# ---------------------------------------------------
# 整合结束
# ===================================================


def main(inputBlob: func.InputStream, outputQueue: func.Out[str]):
    logging.info(f"Python blob trigger function processed blob\\n"
                 f"Name: {inputBlob.name}\\n"
                 f"Size: {inputBlob.length} Bytes")

    conn = None # Initialize conn to None
    try:
        conn_string = os.environ.get("DATABASE_CONNECTION_STRING")

        if not conn_string:
            logging.error("DATABASE_CONNECTION_STRING environment variable is not set. Cannot connect to database.")
            raise ValueError("Database connection string is missing.")

        logging.info(f"Retrieved DB Connection String: {conn_string}")

        # 将连接字符串解析为字典
        db_params = _parse_db_connection_string(conn_string) # 使用辅助函数

        # 使用关键字参数连接
        conn = psycopg2.connect(**db_params)
        logging.info("Successfully connected to PostgreSQL database.")

        # ===================================================
        # 现在 create_table 是同一个文件内的函数，直接调用即可
        create_table(conn_string)
        logging.info("Ensured 'ri_usage' table exists.")
        # ===================================================

        blob_content = inputBlob.read().decode('utf-8')
        csv_reader = csv.reader(io.StringIO(blob_content))

        header = next(csv_reader)
        logging.info(f"CSV Header: {header}")

        header_map = {col.strip(): i for i, col in enumerate(header)}

        report_date = None
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', inputBlob.name)
        if date_match:
            try:
                report_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').strftime('%Y-%m-%d')
                logging.info(f"Parsed report_date '{report_date}' from filename '{inputBlob.name}'.")
            except ValueError:
                logging.warning(f"Could not parse valid date from '{date_match.group(1)}' in filename '{inputBlob.name}'. Using current date as report_date.")
                report_date = datetime.now().strftime('%Y-%m-%d')
        else:
            logging.warning(f"No YYYY-MM-DD date found in filename '{inputBlob.name}'. Using current date as report_date.")
            report_date = datetime.now().strftime('%Y-%m-%d')

        insert_query = """
        INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient, report_date, sku_name, region, term_months)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (subscription_id, resource_id, report_date) DO NOTHING;
        """

        with conn.cursor() as cur:
            rows_processed = 0
            required_columns = ['subscription_id', 'ri_id', 'sku_name', 'region', 'purchase_date', 'term_months', 'utilization_percent', 'email_recipient']
            
            missing_cols = [col for col in required_columns if col not in header_map]
            if missing_cols:
                logging.error(f"CSV Header missing required columns: {missing_cols}. Expected: {required_columns}. Actual: {header}")
                raise ValueError(f"Missing required CSV columns: {missing_cols}")

            for row_num, row in enumerate(csv_reader):
                if len(row) < len(header):
                    logging.warning(f"Skipping malformed row {row_num + 1} (not enough columns matching header): {row}")
                    continue

                try:
                    subscription_id = row[header_map['subscription_id']].strip()
                    resource_id = row[header_map['ri_id']].strip()
                    
                    usage_quantity_str = row[header_map['utilization_percent']].strip()
                    usage_quantity = float(usage_quantity_str) if usage_quantity_str else 0.0

                    usage_start_str = row[header_map['purchase_date']].strip()
                    usage_start_iso = datetime.strptime(usage_start_str, '%Y-%m-%d').isoformat()

                    email_recipient = row[header_map['email_recipient']].strip()

                    sku_name = row[header_map['sku_name']].strip()
                    region = row[header_map['region']].strip()
                    term_months_str = row[header_map['term_months']].strip()
                    term_months = int(term_months_str) if term_months_str.isdigit() else 0


                    cur.execute(insert_query, (
                        subscription_id,
                        resource_id,
                        usage_quantity,
                        usage_start_iso,
                        email_recipient,
                        report_date,
                        sku_name,
                        region,
                        term_months
                    ))
                    if cur.rowcount > 0:
                        rows_processed += 1

                except ValueError as ve:
                    logging.error(f"Data type conversion error for row {row_num + 1} ({row}): {ve}")
                    continue
                except KeyError as ke:
                    logging.error(f"Missing expected column index for key: {ke} in row {row_num + 1} ({row})")
                    continue
                except Exception as e:
                    logging.error(f"Unexpected error processing row {row_num + 1} ({row}): {e}")
                    continue

            conn.commit()
            logging.info(f"Successfully imported {rows_processed} rows from {inputBlob.name} to PostgreSQL.")

        message = json.dumps({"blob_name": inputBlob.name, "status": "data_imported", "timestamp": datetime.now().isoformat()})
        outputQueue.set(message)
        logging.info(f"Sent message to analysis queue: {message}")

    except psycopg2.Error as pg_err:
        logging.error(f"PostgreSQL database error: {pg_err}. Details: {pg_err.diag.message_primary if pg_err.diag else 'N/A'}")
        raise
    except Exception as e:
        logging.error(f"Error during database operation or processing for {inputBlob.name}: {e}")
        raise

    finally:
        if conn:
            conn.close()
            logging.info("PostgreSQL connection closed.")