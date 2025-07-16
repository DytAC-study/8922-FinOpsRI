import json
import os
from datetime import datetime, timedelta
import psycopg2
from collections import defaultdict
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def _parse_db_connection_string(conn_string):
    """
    Parses a PostgreSQL connection string into a dictionary of parameters.
    This handles the DSN format (e.g., "Host=...;Database=...;").
    """
    db_params = {}
    if not conn_string:
        logger.error("Empty connection string provided for parsing.")
        return db_params

    # Split by semicolon and then by equals sign for key-value pairs
    parts = conn_string.strip().split(';')
    for part in parts:
        part = part.strip() # Strip spaces from each part, e.g., " Key = Value "
        if '=' in part:
            key, value = part.split('=', 1)
            # Convert key to lowercase, strip spaces from key/value
            db_params[key.strip().lower()] = value.strip()

    # psycopg2 generally expects 'sslmode' key to be lowercase
    if 'sslmode' in db_params:
        db_params['sslmode'] = db_params['sslmode'].lower()

    logger.debug(f"Parsed DB parameters: {db_params}") # Added debug log for parsed parameters
    return db_params

def generate_alert(underutilized_days, unused_days, UNDERUTILIZED_DAYS_THRESHOLD, UNUSED_DAYS_THRESHOLD):
    """
    Generates an alert string based on underutilized and unused days thresholds.
    Adjusted for single-day analysis where underutilized_days/unused_days will be 0 or 1.
    REMOVED EMOJI CHARACTERS TO PREVENT MOJIBAKE.

    Args:
        underutilized_days (int): Number of underutilized days.
        unused_days (int): Number of unused days.
        UNDERUTILIZED_DAYS_THRESHOLD (int): Threshold for underutilized days to trigger an alert.
        UNUSED_DAYS_THRESHOLD (int): Threshold for unused days to trigger an alert.

    Returns:
        str: A comma-separated string of alerts, or an empty string if no alerts.
    """
    alerts = []
    if unused_days >= UNUSED_DAYS_THRESHOLD:
        alerts.append(f"Unused for {unused_days} day(s)") # Removed emoji
    if underutilized_days >= UNDERUTILIZED_DAYS_THRESHOLD:
        alerts.append(f"Underutilized for {underutilized_days} day(s)") # Removed emoji
    return ", ".join(alerts) if alerts else ""

def analyze_utilization_from_db(
    db_conn_string, min_util_threshold, expiry_warn_days, analysis_win_days,
    underutilized_days_threshold, unused_days_threshold, default_region, default_sku,
    report_date_filter
):
    """
    Analyzes RI utilization data fetched from the PostgreSQL database for a specific report_date.
    Classifies RIs into statuses (healthy, underutilized, unused, expired, expiring_soon)
    and calculates days remaining and generates alerts.

    Args:
        db_conn_string (str): Connection string for the PostgreSQL database.
        min_util_threshold (float): Minimum utilization percentage for 'healthy' status.
        expiry_warn_days (int): Number of days before expiry to trigger a warning.
        analysis_win_days (int): Number of days to look back for analysis (less relevant for single report_date filter).
        underutilized_days_threshold (int): Threshold for consecutive underutilized days to trigger an alert.
        unused_days_threshold (int): Threshold for consecutive unused days to trigger an alert.
        default_region (str): Default region to use if not found in data.
        default_sku (str): Default SKU to use if not found in data.
        report_date_filter (str): The specific 'report_date' (YYYY-MM-DD) to fetch and analyze data for.

    Returns:
        list: A list of dictionaries, each representing an analyzed RI record.
    """
    conn = None
    try:
        # Use the helper function to parse the connection string
        db_params = _parse_db_connection_string(db_conn_string)

        # Add a robust check here: if db_params is empty or doesn't contain 'host', it's likely malformed
        if not db_params or 'host' not in db_params:
            logger.error(f"Failed to parse database connection string. Resulting parameters are: {db_params}")
            raise ValueError("Invalid database connection string format or missing host parameter. Please check DATABASE_CONNECTION_STRING in local.settings.json or environment variables.")

        # Log parameters, hide password for security
        logged_params = {k: v for k, v in db_params.items() if k.lower() != 'password'}
        logger.info(f"Attempting to connect to PostgreSQL with parameters: {logged_params}")

        conn = psycopg2.connect(**db_params) # This is where the parsed dictionary is unpacked

        cursor = conn.cursor()

        # Modified SELECT query to get all relevant columns and filter by report_date
        select_query = """
        SELECT subscription_id, resource_id, usage_quantity, usage_start,
               email_recipient, sku_name, region, term_months, report_date
        FROM ri_usage
        WHERE report_date = %s;
        """
        cursor.execute(select_query, (report_date_filter,))
        ri_data_rows = cursor.fetchall()

        if not ri_data_rows:
            logger.warning(f"No RI data found for report_date '{report_date_filter}' in the database.")
            return []

        # Group data by RI key (subscription_id, resource_id)
        ri_data_by_ri_key = defaultdict(lambda: {
            'data_points': [],
            'sku_name': default_sku,
            'region': default_region,
            'term_months': 0,
            'email_recipient': '', # Initialize to empty string
            'purchase_date': None # Will store the RI's purchase date (from usage_start in DB)
        })

        for row in ri_data_rows:
            # Ensure column order matches the SELECT query
            sub_id, resource_id, usage_quantity, usage_start_str, email_recipient, sku_name, region, term_months, report_date_db = row

            ri_key = (sub_id, resource_id)

            ri_data_by_ri_key[ri_key]['data_points'].append({
                'report_date': report_date_db,
                'usage_quantity': usage_quantity
            })
            # For static RI attributes, set them once or use the first non-default/non-empty value found
            if ri_data_by_ri_key[ri_key]['sku_name'] == default_sku and sku_name:
                ri_data_by_ri_key[ri_key]['sku_name'] = sku_name
            if ri_data_by_ri_key[ri_key]['region'] == default_region and region:
                ri_data_by_ri_key[ri_key]['region'] = region
            if ri_data_by_ri_key[ri_key]['term_months'] == 0 and term_months is not None:
                ri_data_by_ri_key[ri_key]['term_months'] = term_months
            if not ri_data_by_ri_key[ri_key]['email_recipient'] and email_recipient: # Take the first non-empty email recipient
                ri_data_by_ri_key[ri_key]['email_recipient'] = email_recipient
            # Store the purchase_date string directly for later parsing
            if not ri_data_by_ri_key[ri_key]['purchase_date'] and usage_start_str:
                ri_data_by_ri_key[ri_key]['purchase_date'] = usage_start_str

        results = []
        for ri_key, data_payload in ri_data_by_ri_key.items():
            sub_id, resource_id = ri_key

            # Since data is already filtered by report_date, current_day_data will contain the single day's data
            current_day_data = next((dp for dp in data_payload['data_points'] if dp['report_date'] == report_date_filter), None)

            if not current_day_data:
                # This case theoretically shouldn't happen if the initial fetch by report_date_filter was accurate.
                logger.warning(f"No data for RI {ri_key} on report_date {report_date_filter} after initial fetch. Skipping.")
                continue

            # Assuming usage_quantity from DB is already a percentage (e.g., 85.0 for 85%).
            avg_util_percent = current_day_data['usage_quantity']

            status = "healthy"
            if avg_util_percent < min_util_threshold:
                if avg_util_percent == 0:
                    status = "unused"
                else:
                    status = "underutilized"

            # Calculate expiry status
            purchase_date_obj = None
            if data_payload.get('purchase_date'):
                try:
                    # FIX: Change the datetime format string to match 'YYYY-MM-DDTHH:MM:SS'
                    purchase_date_obj = datetime.strptime(data_payload['purchase_date'], '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    logger.warning(f"Could not parse purchase_date '{data_payload['purchase_date']}' for RI {ri_key}. Skipping expiry calculation.")

            days_remaining = -1
            expiry_status = "unknown"
            expiry_date = None # Initialize expiry_date here to ensure it's always defined

            if purchase_date_obj and data_payload['term_months'] and data_payload['term_months'] > 0:
                # Approximate expiry date by adding term_months * (365/12) days
                expiry_date = purchase_date_obj + timedelta(days=int(data_payload['term_months'] * (365.25 / 12)))

                # Calculate days remaining relative to the report_date_filter
                current_report_date_obj = datetime.strptime(report_date_filter, '%Y-%m-%d')
                days_remaining = (expiry_date - current_report_date_obj).days

                if days_remaining <= 0:
                    expiry_status = "expired"
                    status = "expired" # An expired RI should primarily be marked as expired
                elif days_remaining <= expiry_warn_days:
                    expiry_status = "expiring_soon"
                else:
                    expiry_status = "active"
            else:
                expiry_status = "N/A" # Cannot determine expiry without purchase date or term

            # Generate alert message based on today's utilization status
            current_underutilized_days = 1 if status == "underutilized" else 0
            current_unused_days = 1 if status == "unused" else 0
            alert_message = generate_alert(current_underutilized_days, current_unused_days,
                                             underutilized_days_threshold, unused_days_threshold)

            results.append({
                "subscription_id": sub_id,
                "ri_id": resource_id,
                "sku_name": data_payload['sku_name'],
                "region": data_payload['region'],
                "purchase_date": purchase_date_obj.strftime("%Y-%m-%d") if purchase_date_obj else "N/A",
                "end_date": expiry_date.strftime("%Y-%m-%d") if expiry_date else "N/A", # ADDED: End date
                "term_months": data_payload['term_months'],
                "utilization_percent": round(avg_util_percent, 2), # Round to 2 decimal places for presentation
                "days_remaining": days_remaining,
                "status": status,
                "expiry_status": expiry_status,
                "underutilized_days": current_underutilized_days,
                "unused_days": current_unused_days,
                "missing_days": 0, # Not applicable for single-day analysis
                "email_recipient": data_payload['email_recipient'],
                "alert": alert_message,
                "report_date": report_date_filter # Include the report date in the result
            })

        return results

    except Exception as e:
        logger.error(f"Error during RI analysis from database for report_date '{report_date_filter}': {e}")
        raise # Re-raise the exception to propagate it up for Azure Functions runtime to capture.
    finally:
        if conn:
            conn.close()
            logger.info("PostgreSQL connection closed.")