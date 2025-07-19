import json
from datetime import datetime
import psycopg2 # Python PostgreSQL adapter
import logging
import os # To get POSTGRES_CONNECTION_STRING from environment variable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================================================
# Restored: _parse_db_connection_string function
# ---------------------------------------------------
def _parse_db_connection_string(conn_string):
    """
    Parses a PostgreSQL connection string (e.g., "Host=...;Database=...;")
    into a dictionary of parameters for psycopg2.connect.
    """
    db_params = {}
    if not conn_string:
        logger.error("Empty connection string provided for parsing.")
        return db_params

    # Split by semicolon and then by equals sign for key-value pairs
    parts = conn_string.strip().split(';')
    for part in parts:
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            # Convert key to lowercase, strip spaces from key/value
            db_params[key.strip().lower()] = value.strip()

    # psycopg2 generally expects 'sslmode' key to be lowercase
    if 'sslmode' in db_params:
        db_params['sslmode'] = db_params['sslmode'].lower()

    logger.debug(f"Parsed DB parameters: {db_params}")
    return db_params

def create_table(db_conn_string):
    """
    Creates the 'ri_usage' table in the PostgreSQL database if it does not already exist.
    This table stores the flattened Reserved Instance usage data.
    """
    conn = None
    try:
        db_params = _parse_db_connection_string(db_conn_string) # Use the parsing function
        conn = psycopg2.connect(**db_params) # Connect with parsed parameters
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ri_usage (
            subscription_id TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            usage_quantity REAL,
            usage_start DATE NOT NULL,       -- Changed to DATE type
            email_recipient TEXT,
            report_date DATE NOT NULL,       -- Changed to DATE type
            sku_name TEXT,          
            region TEXT,              
            term_months INTEGER,      
            PRIMARY KEY (subscription_id, resource_id, report_date)
        );
        """)
        conn.commit()
        cursor.close()
        logger.info("ri_usage table created or already exists successfully.")
    except Exception as e:
        logger.error(f"Error creating table: {e}", exc_info=True)
        if conn:
            conn.rollback()
        raise # Re-raise to propagate the error
    finally:
        if conn:
            conn.close()

def import_json_data_to_db(db_conn_string, data, date_str, source_filename=""):
    """
    Imports a list of flat JSON records (representing RI usage) into the PostgreSQL database.
    Uses ON CONFLICT DO NOTHING to skip records that already exist based on the primary key.
    
    Args:
        db_conn_string: The database connection string.
        data: A list of dictionaries, where each dictionary is a flat RI usage record.
        date_str: The report date in 'YYYY-MM-DD' format, associated with this batch of data.
        source_filename: Optional; the name of the source file for logging purposes.
    """
    conn = None
    inserted = 0
    skipped = 0
    try:
        report_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() # Convert to date object
        db_params = _parse_db_connection_string(db_conn_string) # Use the parsing function
        conn = psycopg2.connect(**db_params) # Connect with parsed parameters
        cursor = conn.cursor()

        for entry in data:
            try:
                # Assuming 'purchase_date' from JSON data maps to 'usage_start' in DB
                usage_start_str = entry.get("purchase_date")
                usage_start_obj = datetime.strptime(usage_start_str, '%Y-%m-%d').date() # Convert to date object

                cursor.execute("""
                    INSERT INTO ri_usage (
                        subscription_id, resource_id, usage_quantity, usage_start,
                        email_recipient, report_date, sku_name, region, term_months
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (subscription_id, resource_id, report_date) DO NOTHING;
                """, (
                    entry.get("subscription_id"),
                    entry.get("ri_id"),
                    entry.get("utilization_percent"),
                    usage_start_obj,  # Use date object
                    entry.get("email_recipient"),
                    report_date_obj,  # Use date object
                    entry.get("sku_name"),
                    entry.get("region"),
                    entry.get("term_months")
                ))
                # rowcount > 0 indicates a row was inserted (not skipped by ON CONFLICT)
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1 # Entry already existed
            except ValueError as ve:
                logger.error(f"Data type conversion error for entry (RI ID: {entry.get('ri_id')} for {usage_start_str}): {ve}")
                continue # Continue processing other entries
            except Exception as inner_e:
                logger.error(f"Error inserting entry (RI ID: {entry.get('ri_id')} for {usage_start_str}): {inner_e}", exc_info=True)
                continue # Continue processing other entries

        conn.commit() # Commit all insertions in a single transaction
        logger.info(f"[📥] {source_filename} – Inserted: {inserted}, Skipped (already exist): {skipped}")
    except Exception as e:
        logger.error(f"Error importing data for {source_filename}: {e}", exc_info=True)
        if conn:
            conn.rollback() # Rollback in case of a larger import failure
        raise # Re-raise to indicate a larger import failure
    finally:
        if conn:
            conn.close()

# Example usage (for testing purposes, not for production Azure Function)
if __name__ == "__main__":
    # This block will only run when the script is executed directly, not as an Azure Function
    # For local testing, ensure POSTGRES_CONNECTION_STRING is set in your environment
    # Example: export POSTGRES_CONNECTION_STRING="Host=localhost;Database=yourdb;User=youruser;Password=yourpass;Port=5432;"
    
    _test_conn_string = os.getenv('POSTGRES_CONNECTION_STRING')
    if not _test_conn_string:
        logger.error("POSTGRES_CONNECTION_STRING environment variable not set for local testing.")
        exit(1)

    # 1. Test table creation
    logger.info("--- Testing create_table ---")
    try:
        create_table(_test_conn_string)
        logger.info("create_table test successful.")
    except Exception as e:
        logger.error(f"create_table test failed: {e}")
        exit(1)

    # 2. Test data import
    logger.info("--- Testing import_json_data_to_db ---")
    test_data = [
        {
            "subscription_id": "test-sub-001",
            "ri_id": "test-ri-001",
            "sku_name": "TestSKU1",
            "region": "eastus",
            "purchase_date": "2024-01-01",
            "term_months": 12,
            "utilization_percent": 75.5,
            "email_recipient": "test1@example.com"
        },
        {
            "subscription_id": "test-sub-001",
            "ri_id": "test-ri-002",
            "sku_name": "TestSKU2",
            "region": "westus",
            "purchase_date": "2024-02-01",
            "term_months": 24,
            "utilization_percent": 90.0,
            "email_recipient": "test2@example.com"
        },
        # This one should be skipped by ON CONFLICT if run multiple times for the same date
        {
            "subscription_id": "test-sub-001",
            "ri_id": "test-ri-001",
            "sku_name": "TestSKU1",
            "region": "eastus",
            "purchase_date": "2024-01-01",
            "term_months": 12,
            "utilization_percent": 70.0, # Different value, but same PK so should be skipped
            "email_recipient": "test1@example.com"
        }
    ]
    test_date = datetime.now().strftime('%Y-%m-%d')
    try:
        import_json_data_to_db(_test_conn_string, test_data, test_date, "test_data_import.json")
        logger.info("import_json_data_to_db test successful.")
    except Exception as e:
        logger.error(f"import_json_data_to_db test failed: {e}")
        exit(1)

    logger.info("All local tests completed.")