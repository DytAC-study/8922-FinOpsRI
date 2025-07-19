import json
import os
from datetime import datetime, timedelta, date
# For local, we use sqlite3. For Azure, it's psycopg2.
# We'll make the connection string parsing flexible.
import sqlite3
import psycopg2 
from collections import defaultdict
import logging
from calendar import monthrange

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def _parse_db_connection_string(conn_string):
    """
    Parses a database connection string into a dictionary of parameters.
    Supports both PostgreSQL DSN format and basic SQLite path.
    """
    db_params = {}
    if not conn_string:
        logger.error("Empty connection string provided for parsing.")
        return db_params

    # Check for SQLite
    if conn_string.startswith("sqlite:///"):
        db_params['db_type'] = 'sqlite'
        db_params['database'] = conn_string.replace("sqlite:///", "")
        logger.debug(f"Parsed SQLite DB parameters: {db_params}")
        return db_params
    
    # Assume PostgreSQL if not SQLite
    db_params['db_type'] = 'postgresql'
    parts = conn_string.strip().split(';')
    for part in parts:
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            key = key.strip().lower()
            if key == 'host':
                db_params['host'] = value.strip()
            elif key == 'database':
                db_params['dbname'] = value.strip()
            elif key == 'user':
                db_params['user'] = value.strip()
            elif key == 'password':
                db_params['password'] = value.strip()
            elif key == 'port':
                db_params['port'] = value.strip()
            elif key == 'sslmode':
                db_params['sslmode'] = value.strip().lower()
            else:
                db_params[key] = value.strip()

    logger.debug(f"Parsed PostgreSQL DB parameters: {db_params}")
    return db_params


def generate_alert(max_consecutive_underutilized_days, max_consecutive_unused_days,
                   min_underutilized_days, min_unused_days,
                   is_expiring_soon, days_remaining):
    """
    Generates an alert string based on consecutive underutilized/unused days thresholds
    and expiry status.
    """
    alerts = []
    if max_consecutive_unused_days >= min_unused_days:
        alerts.append(f"Unused for {max_consecutive_unused_days} consecutive day(s)")
    if max_consecutive_underutilized_days >= min_underutilized_days:
        alerts.append(f"Underutilized for {max_consecutive_underutilized_days} consecutive day(s)")
    if is_expiring_soon and days_remaining is not None and days_remaining >= 0:
        alerts.append(f"Expires in {days_remaining} day(s)")

    return "; ".join(alerts) if alerts else ""


def analyze_ri_utilization_for_period(
    analysis_period_start_date_str: str,
    analysis_period_end_date_str: str,
    min_util_threshold: float,
    expiry_warn_days: int,
    min_underutilized_days_for_alert: int,
    min_unused_days_for_alert: int,
    default_region: str,
    default_sku: str
) -> list:
    """
    Analyzes RI utilization data for a specified period and aggregates results.
    It considers consecutive underutilized/unused days and expiry status for alerts.
    """
    conn = None
    cursor = None
    try:
        conn_string = os.environ.get('DATABASE_CONNECTION_STRING')
        if not conn_string:
            raise ValueError("DATABASE_CONNECTION_STRING environment variable not set.")

        db_params = _parse_db_connection_string(conn_string)
        
        if db_params['db_type'] == 'sqlite':
            conn = sqlite3.connect(db_params['database'])
            cursor = conn.cursor()
            # SQLite query uses ? placeholders
            query = """
                SELECT
                    subscription_id,
                    resource_id,
                    usage_quantity,
                    report_date,
                    email_recipient,
                    sku_name,
                    region,
                    term_months,
                    purchase_date
                FROM ri_usage
                WHERE report_date BETWEEN ? AND ?
                ORDER BY subscription_id, resource_id, report_date;
            """
        else: # PostgreSQL
            conn = psycopg2.connect(**{k: v for k, v in db_params.items() if k != 'db_type'})
            cursor = conn.cursor()
            # PostgreSQL query uses %s placeholders
            query = """
                SELECT
                    subscription_id,
                    resource_id,
                    usage_quantity,
                    report_date,
                    email_recipient,
                    sku_name,
                    region,
                    term_months,
                    purchase_date
                FROM ri_usage
                WHERE report_date BETWEEN %s AND %s
                ORDER BY subscription_id, resource_id, report_date;
            """
        
        cursor.execute(query, (analysis_period_start_date_str, analysis_period_end_date_str))
        raw_data = cursor.fetchall()

        ri_grouped_data = defaultdict(lambda: defaultdict(dict))
        for row in raw_data:
            # Unpack row based on the order in the SELECT statement
            sub_id, res_id, usage_quantity, report_date_str, email_recipient, sku_name, region, term_months, purchase_date_db_str = row
            
            report_date_obj = datetime.strptime(report_date_str, '%Y-%m-%d').date()
            purchase_date_obj = datetime.strptime(purchase_date_db_str, '%Y-%m-%d').date() 

            ri_grouped_data[(sub_id, res_id)][report_date_obj] = {
                "utilization_percent": usage_quantity,
                "email_recipient": email_recipient,
                "sku_name": sku_name,
                "region": region,
                "term_months": term_months,
                "purchase_date": purchase_date_obj 
            }

        aggregated_results = []

        analysis_period_start_date = datetime.strptime(analysis_period_start_date_str, '%Y-%m-%d').date()
        analysis_period_end_date = datetime.strptime(analysis_period_end_date_str, '%Y-%m-%d').date()
        total_analysis_days = (analysis_period_end_date - analysis_period_start_date).days + 1

        for (sub_id, resource_id), daily_data in ri_grouped_data.items():
            current_underutilized_days_consecutive = 0
            current_unused_days_consecutive = 0
            max_underutilized_sequence = 0
            max_unused_sequence = 0
            
            total_utilization_sum = 0.0
            valid_utilization_days_count = 0 # Days for which we have data within the analysis period
            
            total_underutilized_days_period_actual = 0
            total_unused_days_period_actual = 0

            data_payload = {
                "sku_name": default_sku,
                "region": default_region,
                "term_months": "N/A",
                "email_recipient": "N/A",
                "purchase_date": None 
            }

            expected_dates_in_period = set(analysis_period_start_date + timedelta(days=i) for i in range(total_analysis_days))
            actual_dates_in_data = set(daily_data.keys())
            
            missing_dates_list = sorted(list(expected_dates_in_period - actual_dates_in_data))
            missing_days_count = len(missing_dates_list)
            
            if missing_days_count > 0:
                logger.debug(f"RI {resource_id} (Sub: {sub_id}) missing data for {missing_days_count} days: {missing_dates_list}")

            first_actual_data_date_in_period = None
            last_actual_data_date_in_period = None
            if actual_dates_in_data:
                first_actual_data_date_in_period = min(actual_dates_in_data)
                last_actual_data_date_in_period = max(actual_dates_in_data)

            current_date = analysis_period_start_date
            while current_date <= analysis_period_end_date:
                if current_date in daily_data:
                    day_utilization = daily_data[current_date]["utilization_percent"]
                    data_payload.update({
                        "sku_name": daily_data[current_date]["sku_name"],
                        "region": daily_data[current_date]["region"],
                        "term_months": daily_data[current_date]["term_months"],
                        "email_recipient": daily_data[current_date]["email_recipient"],
                        "purchase_date": daily_data[current_date]["purchase_date"]
                    })
                    
                    if day_utilization < min_util_threshold * 100:
                        current_underutilized_days_consecutive += 1
                        total_underutilized_days_period_actual += 1
                        if day_utilization == 0:
                            current_unused_days_consecutive += 1
                            total_unused_days_period_actual += 1
                        else:
                            current_unused_days_consecutive = 0
                    else:
                        current_underutilized_days_consecutive = 0
                        current_unused_days_consecutive = 0

                    max_underutilized_sequence = max(max_underutilized_sequence, current_underutilized_days_consecutive)
                    max_unused_sequence = max(max_unused_sequence, current_unused_days_consecutive)

                    total_utilization_sum += day_utilization
                    valid_utilization_days_count += 1
                else:
                    current_underutilized_days_consecutive = 0
                    current_unused_days_consecutive = 0
                
                current_date += timedelta(days=1)

            is_data_continuous_from_start = False
            if first_actual_data_date_in_period and last_actual_data_date_in_period:
                expected_days_in_span = (last_actual_data_date_in_period - first_actual_data_date_in_period).days + 1
                if valid_utilization_days_count == expected_days_in_span:
                    is_data_continuous_from_start = True

            overall_utilization_percent = (total_utilization_sum / valid_utilization_days_count) if valid_utilization_days_count > 0 else 0.0

            expiry_date_ri_obj = None
            is_expiring_soon = False
            days_remaining = -1

            purchase_date_obj = data_payload.get('purchase_date')
            term_months_val = data_payload.get('term_months')

            if purchase_date_obj and isinstance(purchase_date_obj, date) and term_months_val is not None:
                try:
                    expiry_year = purchase_date_obj.year + (term_months_val // 12)
                    expiry_month = purchase_date_obj.month + (term_months_val % 12)
                    if expiry_month > 12:
                        expiry_year += (expiry_month - 1) // 12
                        expiry_month = (expiry_month - 1) % 12 + 1
                    
                    try:
                        expiry_date_ri_obj = date(expiry_year, expiry_month, purchase_date_obj.day)
                    except ValueError:
                        last_day_of_month = monthrange(expiry_year, expiry_month)[1]
                        expiry_date_ri_obj = date(expiry_year, expiry_month, last_day_of_month)

                    days_remaining = (expiry_date_ri_obj - analysis_period_end_date).days
                    if days_remaining <= expiry_warn_days and days_remaining >= 0:
                        is_expiring_soon = True
                except Exception as e:
                    logger.warning(f"Error calculating expiry date for RI {resource_id} (Purchase: {purchase_date_obj}, Term: {term_months_val}): {e}")
                    expiry_date_ri_obj = None

            expiry_status = "active"
            if expiry_date_ri_obj:
                if analysis_period_end_date >= expiry_date_ri_obj:
                    expiry_status = "expired"
                elif is_expiring_soon:
                    expiry_status = "expiring_soon"
            
            status = "healthy"

            if missing_days_count == total_analysis_days:
                status = "No Data"
            elif missing_days_count > 0 and not is_data_continuous_from_start:
                status = "Partial Data"
            else:
                if overall_utilization_percent == 0:
                    status = "unused"
                elif overall_utilization_percent < min_util_threshold * 100:
                    status = "underutilized"
                # else status remains "healthy"

            alert_message = generate_alert(
                max_underutilized_sequence,
                max_unused_sequence,
                min_underutilized_days_for_alert,
                min_unused_days_for_alert,
                is_expiring_soon,
                days_remaining
            )

            aggregated_results.append({
                "ri_id": resource_id,
                "subscription_id": sub_id,
                "sku_name": data_payload['sku_name'],
                "region": data_payload['region'],
                "purchase_date": purchase_date_obj.strftime("%Y-%m-%d") if purchase_date_obj else "N/A",
                "end_date": expiry_date_ri_obj.strftime("%Y-%m-%d") if expiry_date_ri_obj else "N/A",
                "term_months": data_payload['term_months'],
                "utilization_percent_period": round(overall_utilization_percent, 2),
                "days_remaining": days_remaining,
                "status": status,
                "expiry_status": expiry_status,
                "total_underutilized_days_period": total_underutilized_days_period_actual,
                "total_unused_days_period": total_unused_days_period_actual,
                "missing_days": missing_days_count,
                "email_recipient": data_payload['email_recipient'],
                "alert": alert_message,
                "analysis_period_start": analysis_period_start_date_str,
                "analysis_period_end": analysis_period_end_date_str,
                "max_consecutive_underutilized_days": max_underutilized_sequence,
                "max_consecutive_unused_days": max_unused_sequence,
            })

        logger.info(f"RI analysis completed for period. Found {len(aggregated_results)} aggregated RI records.")
        return aggregated_results

    except Exception as e:
        logger.error(f"Error during RI analysis for period {analysis_period_start_date_str} to {analysis_period_end_date_str}: {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

# This part is for local execution when analyze_ri_utilization.py is run directly
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv() # Load .env variables for local run

    # Define analysis period from environment variables or defaults
    analysis_period_days = int(os.getenv("ANALYSIS_PERIOD_DAYS", "30"))
    min_util_threshold = float(os.getenv("MIN_UTIL_THRESHOLD", "0.8"))
    expiry_warn_days = int(os.getenv("EXPIRY_WARN_DAYS", "90"))
    min_underutilized_days_for_alert = int(os.getenv("MIN_UNDERUTILIZED_DAYS_FOR_ALERT", "5"))
    min_unused_days_for_alert = int(os.getenv("MIN_UNUSED_DAYS_FOR_ALERT", "3"))
    default_region = os.getenv("DEFAULT_REGION", "unknown")
    default_sku = os.getenv("DEFAULT_SKU", "unknown")

    # Determine the analysis end date (e.g., yesterday)
    analysis_end_date = datetime.utcnow().date() - timedelta(days=1)
    analysis_start_date = analysis_end_date - timedelta(days=analysis_period_days - 1)

    analysis_results = analyze_ri_utilization_for_period(
        analysis_start_date.strftime('%Y-%m-%d'),
        analysis_end_date.strftime('%Y-%m-%d'),
        min_util_threshold,
        expiry_warn_days,
        min_underutilized_days_for_alert,
        min_unused_days_for_alert,
        default_region,
        default_sku
    )

    # For local testing, save results to a JSON file
    output_path = f"data/ri_utilization_summary_{analysis_end_date.strftime('%Y-%m-%d')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, indent=2)
    logger.info(f"[✅] RI analysis summary saved to {output_path}")

