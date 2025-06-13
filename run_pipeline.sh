#!/bin/bash
set -e

echo "🚀 Activating virtual environment..."
source .venv/bin/activate

echo "🔍 Step 1: Import RI JSONs to DB..."
python import_to_db.py --all

echo "📊 Step 2: Analyze RI Utilization..."
python analyze_ri_utilization.py

echo "📧 Step 3: Send Email Reports..."
python send_html_reports.py

echo "✅ All steps completed."
