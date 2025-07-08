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

    conn = None # Initialize conn to None
    try:
        conn_string = os.environ.get("DATABASE_CONNECTION_STRING") # Use .get() to avoid KeyError if not set

        if not conn_string:
            logging.error("DATABASE_CONNECTION_STRING environment variable is not set. Cannot connect to database.")
            raise ValueError("Database connection string is missing.") # Raise a specific error for clarity

        # --- 新增的诊断日志 ---
        logging.info(f"Retrieved DB Connection String (first 20 chars): {conn_string[:20]}...")
        # --- 新增的诊断日志 ---

        blob_content = inputBlob.read().decode('utf-8')
        csv_reader = csv.reader(io.StringIO(blob_content))

        header = next(csv_reader)
        logging.info(f"CSV Header: {header}")

        header_map = {col.strip(): i for i, col in enumerate(header)}

        insert_query = """
        INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (subscription_id, resource_id, usage_start) DO NOTHING;
        """

        # --- 连接数据库的 try-except 块 ---
        try:
            conn = psycopg2.connect(conn_string) # Attempt to connect to the database
            logging.info("Successfully connected to PostgreSQL database.") # Log successful connection
            with conn.cursor() as cur:
                rows_processed = 0
                required_columns = ['subscription_id', 'ri_id', 'utilization_percent', 'purchase_date', 'email_recipient']
                
                # Check for missing required columns in the header once
                missing_cols = [col for col in required_columns if col not in header_map]
                if missing_cols:
                    logging.error(f"CSV Header missing required columns: {missing_cols}. Expected: {required_columns}. Actual: {header}")
                    raise ValueError(f"Missing required CSV columns: {missing_cols}")

                for row_num, row in enumerate(csv_reader):
                    if len(row) < len(header):
                         logging.warning(f"Skipping malformed row {row_num + 2} (not enough columns matching header): {row}")
                         continue

                    try:
                        subscription_id = row[header_map['subscription_id']].strip()
                        ri_id = row[header_map['ri_id']].strip()
                        utilization_percent = float(row[header_map['utilization_percent']].strip())
                        purchase_date_str = row[header_map['purchase_date']].strip()
                        email_recipient = row[header_map['email_recipient']].strip()

                        purchase_date_iso = datetime.strptime(purchase_date_str, '%Y-%m-%d').isoformat()

                        cur.execute(insert_query, (
                            subscription_id,
                            ri_id,
                            utilization_percent,
                            purchase_date_iso,
                            email_recipient
                        ))
                        if cur.rowcount > 0:
                            rows_processed += 1

                    except ValueError as ve:
                        logging.error(f"Data type conversion error for row {row_num + 2} ({row}): {ve}")
                        continue
                    except KeyError as ke:
                        logging.error(f"Missing expected column index for key: {ke} in row {row_num + 2} ({row})")
                        continue
                    except Exception as e:
                        logging.error(f"Unexpected error processing row {row_num + 2} ({row}): {e}")
                        continue

                conn.commit()
                logging.info(f"Successfully imported {rows_processed} rows from {inputBlob.name} to PostgreSQL.")

            message = json.dumps({"blob_name": inputBlob.name, "status": "data_imported", "timestamp": datetime.now().isoformat()})
            outputQueue.set(message)
            logging.info(f"Sent message to analysis queue: {message}")

        except psycopg2.Error as pg_err: # Catch specific psycopg2 errors for database issues
            logging.error(f"PostgreSQL database error: {pg_err}. Details: {pg_err.diag.message_primary if pg_err.diag else 'N/A'}")
            raise # Re-raise for Azure Functions to log the full exception
        except Exception as e: # Catch any other exceptions during database connection or operations
            logging.error(f"Error during database operation or processing for {inputBlob.name}: {e}")
            raise # Re-raise for Azure Functions to log the full exception

    except Exception as e: # Catch exceptions outside of the database operations (e.g., blob read, env var missing)
        logging.error(f"Overall error in import_to_db_func processing {inputBlob.name}: {e}")
        raise # Ensure all exceptions are re-raised for detailed logging in Azure

    finally:
        if conn:
            conn.close() # Ensure connection is closed even if errors occur
            logging.info("PostgreSQL connection closed.")