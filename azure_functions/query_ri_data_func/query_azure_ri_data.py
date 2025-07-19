import os
import json
from datetime import datetime, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.consumption import ConsumptionManagementClient
import logging

logger = logging.getLogger(__name__)

# Default values for placeholder data (these are mostly for local mock data, but kept for completeness)
DEFAULT_TERM_MONTHS = 12
DAYS_BEFORE_TODAY = 180 # Used for example purchase date calculation

def fetch_subscriptions():
    """
    Fetches a list of Azure subscription IDs accessible by the authenticated identity.
    Requires 'Reader' role or similar on the subscriptions.
    """
    credential = DefaultAzureCredential()
    client = SubscriptionClient(credential)
    return [sub.subscription_id for sub in client.subscriptions.list()]

def fetch_tagged_emails(subscription_id):
    """
    Fetches resource tags, specifically looking for an 'email' tag,
    for resources within a given subscription.
    This is used to map RIs to recipient email addresses.
    """
    credential = DefaultAzureCredential()
    client = ResourceManagementClient(credential, subscription_id)
    resources = client.resources.list(filter="tagName eq 'email'")
    email_map = {}
    for res in resources:
        email = res.tags.get("email") if res.tags else None
        if email:
            email_map[res.id.lower()] = email
    return email_map

def fetch_usage_details(subscription_id, target_date: date):
    """
    Fetches Azure consumption usage details for a specific target date.
    Filters for Reserved Instance usage.
    Returns a list of daily records.
    """
    credential = DefaultAzureCredential()
    client = ConsumptionManagementClient(credential, subscription_id)
    
    # Query for the specific target_date
    start_date_str = target_date.isoformat()
    # End date is the next day, exclusive, to cover the whole target_date
    end_date_str = (target_date + timedelta(days=1)).isoformat() 

    daily_records_list = []
    try:
        # Use a generator for potentially large results
        # Filter for Reservation usage if applicable, or process all and filter later
        for usage in client.usage_details.list(
            scope=f"/subscriptions/{subscription_id}",
            expand="meterDetails,additionalInfo",
            filter=f"properties/usageStart ge '{start_date_str}' and properties/usageEnd lt '{end_date_str}'", # Use lt for end_date to get only target_date
            metric="ActualCost" # Or 'AmortizedCost'
        ):
            ri_id = usage.properties.get("instanceId", usage.properties.get("resourceId", "unknown_ri"))
            quantity = usage.properties.get("quantity", 0)
            # Ensure usage_date is the actual report date for the record
            usage_date_str = usage.properties.get("usageStart", target_date.isoformat())
            sku = usage.properties.get("meterDetails", {}).get("meterName", "unknown_sku")
            region = usage.properties.get("resourceLocation", "unknown_region")
            
            # Placeholder for term_months and purchase_date for real data
            # In a real scenario, these would come from Reservation APIs or tags
            term_months = DEFAULT_TERM_MONTHS # Placeholder
            purchase_date = (target_date - timedelta(days=DAYS_BEFORE_TODAY)).isoformat() # Placeholder

            daily_records_list.append({
                "subscription_id": subscription_id,
                "resource_id": ri_id,
                "usage_quantity": quantity,
                "report_date": datetime.fromisoformat(usage_date_str.replace('Z', '+00:00')).date().isoformat(), # Ensure it's just the date
                "sku_name": sku,
                "region": region,
                "term_months": term_months,
                "purchase_date": purchase_date # This will be the same for all daily records from this fetch
            })
    except Exception as e:
        logger.error(f"[❌] Error fetching usage details for subscription {subscription_id} on {target_date}: {e}", exc_info=True)
        raise

    return daily_records_list

