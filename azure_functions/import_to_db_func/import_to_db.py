import json
from datetime import datetime
import psycopg2 # Python PostgreSQL adapter
# Removed: import sqlite3
# Removed: DB_PATH = "ri_data.db"
# Removed: from dotenv import load_dotenv
# Removed: from pathlib import Path
# Removed: import argparse

def create_table(db_conn_string):
    """
    Creates the 'ri_usage' table in the PostgreSQL database if it does not already exist.
    This table stores the flattened Reserved Instance usage data.
    """
    conn = None
    try:
        conn = psycopg2.connect(db_conn_string)
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
    except Exception as e:
        print(f"Error creating table: {e}")
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
    usage_start = f"{date_str}T00:00:00Z"

    try:
        conn = psycopg2.connect(db_conn_string)
        cursor = conn.cursor()

        for entry in data:
            try:
                # INSERT ... ON CONFLICT DO NOTHING is a PostgreSQL feature
                # that prevents errors if a primary key violation occurs.
                cursor.execute("""
                INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (subscription_id, resource_id, usage_start) DO NOTHING;
                """, (
                    entry.get("subscription_id"),
                    entry.get("ri_id"),
                    entry.get("utilization_percent"), # This is the 'quantity' for RI usage percentage
                    usage_start,
                    entry.get("email_recipient")
                ))
                # rowcount > 0 indicates a row was inserted (not skipped by ON CONFLICT)
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1 # Entry already existed
            except Exception as inner_e:
                print(f"Error inserting entry {entry.get('ri_id')} for {usage_start}: {inner_e}")
                # Log the error but continue processing other entries if possible
                # Depending on error handling policy, you might choose to break here.

        conn.commit() # Commit all insertions in a single transaction
        print(f"[📥] {source_filename} – Inserted: {inserted}, Skipped (already exist): {skipped}")
    except Exception as e:
        print(f"Error importing data for {source_filename}: {e}")
        raise # Re-raise to indicate a larger import failure
    finally:
        if conn:
            conn.close()