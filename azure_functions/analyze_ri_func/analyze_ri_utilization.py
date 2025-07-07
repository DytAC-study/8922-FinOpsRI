import json
import os
from datetime import datetime, timedelta
import psycopg2 # Python PostgreSQL adapter
from collections import defaultdict

# Removed: from dotenv import load_dotenv (Azure Functions handle environment variables)
# Removed: local file paths and output path (output handled by __init__.py to Blob Storage)

def generate_alert(underutilized_days, unused_days, UNDERUTILIZED_DAYS_THRESHOLD, UNUSED_DAYS_THRESHOLD):
    """
    Generate alert string based on underutilized and unused days thresholds.
    """
    alerts = []
    if unused_days >= UNUSED_DAYS_THRESHOLD:
        alerts.append(f"❗ unused for {unused_days} days")
    if underutilized_days >= UNDERUTILIZED_DAYS_THRESHOLD:
        alerts.append(f"⚠️ underutilized for {underutilized_days} days")
    return ", ".join(alerts) if alerts else ""

def analyze_utilization_from_db(
    db_conn_string, min_util_threshold, expiry_warn_days, analysis_win_days,
    underutilized_days_threshold, unused_days_threshold, default_region, default_sku
):
    """
    Analyzes RI utilization data fetched from the PostgreSQL database.
    Classifies RIs into statuses (healthy, underutilized, unused, expired, expiring_soon)
    and generates alerts.

    Args:
        db_conn_string (str): Connection string for the PostgreSQL database.
        min_util_threshold (float): Minimum utilization percentage for 'healthy' status.
        expiry_warn_days (int): Number of days before expiry to trigger a warning.
        analysis_win_days (int): Number of past days to consider for utilization analysis.
        underutilized_days_threshold (int): Days of underutilization to trigger an alert.
        unused_days_threshold (int): Days of non-usage to trigger an alert.
        default_region (str): Default region to use if not found in data.
        default_sku (str): Default SKU to use if not found in data.

    Returns:
        list: A list of dictionaries, each representing an analyzed RI record.
    """
    conn = None
    results = []
    now = datetime.now()
    # Calculate the start date for the analysis window
    analysis_start_date = now - timedelta(days=analysis_win_days)

    try:
        conn = psycopg2.connect(db_conn_string)
        cursor = conn.cursor()

        # Fetch all relevant RI usage records within the analysis window.
        # This query assumes `usage_start` is stored as an ISO formatted string.
        # The `ORDER BY` ensures we can process records chronologically per RI.
        cursor.execute("""
        SELECT
            subscription_id,
            resource_id,
            usage_quantity,
            usage_start,
            email_recipient
        FROM ri_usage
        WHERE usage_start >= %s
        ORDER BY resource_id, usage_start;
        """, (analysis_start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),))

        raw_records = cursor.fetchall()

        # Group raw records by RI to perform per-RI analysis
        ri_grouped_data = defaultdict(lambda: {
            'records': [],
            'latest_email': "noreply@example.com", # Default email
            'subscription_id': None,
            'sku_name': default_sku, # Placeholder, ideally derived from data
            'region': default_region  # Placeholder, ideally derived from data
        })

        for row in raw_records:
            sub_id, resource_id, usage_quantity, usage_start_str, email_recipient = row
            usage_date = datetime.strptime(usage_start_str, "%Y-%m-%dT%H:%M:%SZ").date()

            key = (sub_id, resource_id)
            ri_grouped_data[key]['records'].append({
                "date": usage_date,
                "quantity": usage_quantity,
            })
            # Update latest details for the RI
            ri_grouped_data[key]['latest_email'] = email_recipient
            ri_grouped_data[key]['subscription_id'] = sub_id
            # NOTE: SKU and Region should ideally come from Azure RI data, not hardcoded defaults.
            # If your 'fetch_usage_details' can provide these per RI, pass them through.
            # For now, using defaults.

        # Perform analysis for each grouped RI
        for (sub_id, resource_id), data_payload in ri_grouped_data.items():
            daily_usages = {r['date']: r['quantity'] for r in data_payload['records']}
            latest_email_recipient = data_payload['latest_email']

            total_usage = 0
            days_with_data = 0
            unused_days = 0
            underutilized_days = 0
            missing_days = 0 # Days within analysis window for which no data was found

            # Iterate through the analysis window (from 'now' backwards)
            for i in range(analysis_win_days):
                current_analysis_date = now.date() - timedelta(days=i)
                qty = daily_usages.get(current_analysis_date)
                if qty is not None: # Data exists for this day
                    total_usage += qty
                    days_with_data += 1
                    if qty == 0:
                        unused_days += 1
                    elif qty < min_util_threshold:
                        underutilized_days += 1
                else: # No data found for this specific day in the analysis window
                    missing_days += 1

            # Calculate average utilization over days with data
            avg_util_percent = round(total_usage / days_with_data, 2) if days_with_data > 0 else 0

            # Determine RI status based on average utilization
            status = ""
            if avg_util_percent >= min_util_threshold:
                status = "healthy"
            elif avg_util_percent == 0 and unused_days > 0: # Ensure it's truly unused for some days
                status = "unused"
            elif avg_util_percent < min_util_threshold:
                status = "underutilized"

            # Check expiry status (this is still based on placeholder dates if real RI data not available)
            # You should integrate actual RI purchase/expiry dates from Azure API if possible.
            # For demonstration, assuming a purchase 180 days ago and a 1-year term.
            purchase_date_placeholder = now.date() - timedelta(days=180) # Example: Purchased 6 months ago
            expiry_date_placeholder = purchase_date_placeholder + timedelta(days=365) # Example: 1-year term
            days_remaining = (expiry_date_placeholder - now.date()).days

            expiry_status = ""
            if days_remaining < 0:
                expiry_status = "expired"
            elif days_remaining <= expiry_warn_days:
                expiry_status = "expiring_soon"
            else:
                expiry_status = "active"

            # Generate alert message
            alert_message = generate_alert(underutilized_days, unused_days,
                                            underutilized_days_threshold, unused_days_threshold)

            # Add the analyzed RI record to results
            results.append({
                "subscription_id": sub_id,
                "ri_id": resource_id,
                "sku_name": data_payload['sku_name'], # Use derived SKU or default
                "region": data_payload['region'],     # Use derived region or default
                "purchase_date": purchase_date_placeholder.strftime("%Y-%m-%d"),
                "term_months": 12, # Placeholder
                "utilization_percent": avg_util_percent,
                "days_remaining": days_remaining,
                "status": status,
                "expiry_status": expiry_status,
                "underutilized_days": underutilized_days,
                "unused_days": unused_days,
                "missing_days": missing_days,
                "email_recipient": latest_email_recipient,
                "alert": alert_message
            })

        return results

    except Exception as e:
        print(f"Error during RI analysis from database: {e}")
        raise # Re-raise to propagate the error
    finally:
        if conn:
            conn.close()