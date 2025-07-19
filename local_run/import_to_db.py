# import_to_db.py – Imports daily RI utilization data into SQLite DB

import sqlite3
import json
import os
from pathlib import Path
import argparse
from datetime import datetime

DB_PATH = "ri_data.db"
DATA_DIR = "data" # Directory where query_azure_ri_data.py saves its output

def create_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # --- MODIFIED: Updated table schema to match new data structure (consistent with Azure Functions) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ri_usage (
        subscription_id TEXT,
        resource_id TEXT,
        usage_quantity REAL,
        report_date TEXT,      -- Daily report date for this usage record
        email_recipient TEXT,
        sku_name TEXT,
        region TEXT,
        term_months INTEGER,
        purchase_date TEXT,    -- RI purchase date (fixed for an RI)
        PRIMARY KEY (subscription_id, resource_id, report_date)
    )
    """)
    conn.commit()
    conn.close()

def import_json_daily_data(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    skipped = 0

    for entry in data:
        try:
            # --- MODIFIED: Insert new fields (consistent with query_azure_ri_data.py output) ---
            cursor.execute("""
            INSERT INTO ri_usage (
                subscription_id, resource_id, usage_quantity, report_date,
                email_recipient, sku_name, region, term_months, purchase_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry["subscription_id"],
                entry["resource_id"],
                entry["usage_quantity"],
                entry["report_date"],
                entry["email_recipient"],
                entry["sku_name"],
                entry["region"],
                entry["term_months"],
                entry["purchase_date"]
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            # This means a record for this (subscription_id, resource_id, report_date) already exists
            skipped += 1
        except KeyError as e:
            print(f"Error: Missing key in JSON entry: {e}. Entry: {entry}")
            skipped += 1 # Skip malformed entries

    conn.commit()
    conn.close()
    print(f"[📥] {Path(filepath).name} – Inserted: {inserted}, Skipped (already exist/malformed): {skipped}")

def import_all_files():
    # --- MODIFIED: Look for new daily summary file pattern and import only the latest ---
    files = sorted(Path(DATA_DIR).glob("azure_ri_usage_daily_summary_*.json"))
    if not files:
        print(f"No daily summary files found in {DATA_DIR}. Please run query_azure_ri_data.py first.")
        return
    
    # Import only the latest generated daily summary file
    latest_file = files[-1]
    print(f"Importing latest daily summary file: {latest_file.name}")
    import_json_daily_data(latest_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import RI daily utilization JSONs to SQLite DB")
    parser.add_argument("--file", help="Import a single JSON file")
    parser.add_argument("--all", action="store_true", help="Import the latest daily JSON file from ./data")

    args = parser.parse_args()

    create_table() # Ensure table exists before importing

    if args.all:
        import_all_files()
    elif args.file:
        if Path(args.file).exists():
            import_json_daily_data(args.file)
        else:
            print(f"Error: File not found at {args.file}")
    else:
        print("Please provide --file <filename> or --all")

