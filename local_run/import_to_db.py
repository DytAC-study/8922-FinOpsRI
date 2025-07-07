# import_to_db.py – Modified for flat JSON format

import sqlite3
import json
import os
from pathlib import Path
import argparse
from datetime import datetime

DB_PATH = "ri_data.db"

def create_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ri_usage (
        subscription_id TEXT,
        resource_id TEXT,
        usage_quantity REAL,
        usage_start TEXT,
        email_recipient TEXT,
        PRIMARY KEY (subscription_id, resource_id, usage_start)
    )
    """)
    conn.commit()
    conn.close()

def parse_date_from_filename(filename):
    try:
        return filename.split("_summary_")[1].replace(".json", "")
    except IndexError:
        return "unknown"

def import_json_flat(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    date_str = parse_date_from_filename(Path(filepath).name)
    usage_start = f"{date_str}T00:00:00Z"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    skipped = 0

    for entry in data:
        try:
            cursor.execute("""
            INSERT INTO ri_usage (subscription_id, resource_id, usage_quantity, usage_start, email_recipient)
            VALUES (?, ?, ?, ?, ?)
            """, (
                entry["subscription_id"],
                entry["ri_id"],
                entry["utilization_percent"],
                usage_start,
                entry["email_recipient"]
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    conn.close()
    print(f"[📥] {Path(filepath).name} – Inserted: {inserted}, Skipped (already exist): {skipped}")

def import_all_files():
    files = sorted(Path("data").glob("azure_ri_usage_summary_*.json"))
    for f in files:
        import_json_flat(f)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Import a single JSON file")
    parser.add_argument("--all", action="store_true", help="Import all JSON files from ./data")

    args = parser.parse_args()

    create_table()

    if args.all:
        import_all_files()
    elif args.file:
        import_json_flat(args.file)
    else:
        print("Please provide --file <filename> or --all")
