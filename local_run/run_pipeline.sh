#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

echo "🚀 Activating Python virtual environment..."
# Assuming .venv is located in the project root directory (one level up from local_run/).
# Adjust this path if your .venv is located elsewhere.
source ../.venv/bin/activate

echo "Starting the local RI Utilization Report Pipeline..."

# Step 1: Query Azure RI Data.
# This script is expected to fetch data and save it into the 'data/' directory within 'local_run/'.
echo "🔍 Step 1: Querying Azure RI Data and saving to local JSONs..."
python query_azure_ri_data.py

# Step 2: Import RI JSONs into the SQLite Database.
# This script reads JSONs from 'local_run/data/' and populates 'local_run/ri_data.db'.
echo "📥 Step 2: Importing RI JSONs into the local SQLite DB..."
python import_to_db.py --all

# Step 3: Analyze RI Utilization.
# This script reads from 'local_run/ri_data.db', performs analysis,
# and outputs summary JSONs to 'local_run/data/'.
echo "📊 Step 3: Analyzing RI Utilization from DB..."
python analyze_ri_utilization.py

# Step 4: Generate and Send Email Reports.
# This script reads analysis results from 'local_run/data/',
# generates HTML/CSV reports in 'local_run/email_reports/',
# and dispatches emails using the configured method (SMTP or Logic App endpoint from .env).
echo "📧 Step 4: Generating and Sending Email Reports..."
python send_html_reports.py

echo "✅ Local pipeline execution completed successfully."

# Deactivate the virtual environment upon script completion.
deactivate