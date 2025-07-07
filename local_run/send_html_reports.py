import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from email_utils import send_email
from collections import defaultdict

load_dotenv()

EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")
SUMMARY_DIR = Path("data")
REPORT_DIR = Path("email_reports")
REPORT_DIR.mkdir(exist_ok=True)

# 获取最新的 ri_utilization_summary_*.json 文件
summary_files = sorted(SUMMARY_DIR.glob("ri_utilization_summary_*.json"))
if not summary_files:
    print("❌ No summary file found.")
    exit(1)

latest_summary = summary_files[-1]
summary_date = latest_summary.stem.replace("ri_utilization_summary_", "")

with latest_summary.open("r", encoding="utf-8") as f:
    records = json.load(f)

grouped = {}
for rec in records:
    email = rec.get("email_recipient")
    if email:
        grouped.setdefault(email, []).append(rec)

def generate_html_table(data):
    rows = ""
    alerts = ""
    for r in data:
        status = r["status"]
        utilization = r.get("utilization_percent", "-")
        days = r.get("days_remaining", "-")
        color = "#d4edda"  # healthy: light green
        if status == "underutilized":
            color = "#fff3cd"  # light orange
        elif status == "unused":
            color = "#f8d7da"  # light red

        row = f"""
        <tr style="background-color:{color}">
            <td>{r['ri_id']}</td>
            <td>{r['sku_name']}</td>
            <td>{r['region']}</td>
            <td>{utilization}</td>
            <td>{days}</td>
            <td>{status}</td>
            <td>{r['expiry_status']}</td>
        </tr>
        """
        rows += row

        if status == "underutilized":
            alerts += (
                f"<p style='color:#856404;'>⚠️ {r['ri_id']} is underutilized for "
                f"{r.get('underutilized_days', '?')} days.</p>\n"
            )
        elif status == "unused":
            alerts += (
                f"<p style='color:#721c24;'>❗ {r['ri_id']} is unused for "
                f"{r.get('unused_days', '?')} days.</p>\n"
            )


    return f"""
    <html>
    <body>
    <h3>Azure Reserved Instance Report – {summary_date}</h3>
    {alerts}
    <table border="1" cellpadding="6" cellspacing="0">
        <tr>
            <th>RI ID</th>
            <th>SKU</th>
            <th>Region</th>
            <th>Utilization (%)</th>
            <th>Days Remaining</th>
            <th>Status</th>
            <th>Expiry</th>
        </tr>
        {rows}
    </table>
    </body>
    </html>
    """

def export_csv(data, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "ri_id", "sku_name", "region", "utilization_percent",
            "days_remaining", "status", "expiry_status"
        ])
        writer.writeheader()
        for r in data:
            writer.writerow({
                "ri_id": r["ri_id"],
                "sku_name": r["sku_name"],
                "region": r["region"],
                "utilization_percent": r.get("utilization_percent"),
                "days_remaining": r.get("days_remaining"),
                "status": r["status"],
                "expiry_status": r["expiry_status"]
            })

# Send per recipient
for recipient, data in grouped.items():
    safe_name = recipient.replace("@", "_at_").replace(".", "_")
    html_file = REPORT_DIR / f"{safe_name}_{summary_date}.html"
    csv_file = REPORT_DIR / f"{safe_name}_{summary_date}.csv"

    html_content = generate_html_table(data)
    with html_file.open("w", encoding="utf-8") as f:
        f.write(html_content)

    export_csv(data, csv_file)
    print(f"📧 HTML + CSV report generated for {recipient}: {html_file}, {csv_file}")

    # Region-wise alert count
    region_alerts = defaultdict(int)
    for r in data:
        if r["status"] in ("underutilized", "unused"):
            region_alerts[r["region"]] += 1
    total_alerts = sum(region_alerts.values())
    region_summary = ", ".join(f"{region}: {count}" for region, count in region_alerts.items())

    subject = f"RI Utilization Report – {summary_date} ({total_alerts} alerts: {region_summary})"

    send_email(
        recipient=recipient,
        subject=subject,
        html_body=html_content,
        attachment=csv_file  # for logicapp mode, content will be encoded
    )