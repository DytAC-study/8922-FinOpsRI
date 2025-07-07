import os
import json
from datetime import datetime, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.consumption import ConsumptionManagementClient

# Removed: from dotenv import load_dotenv (Azure Functions handle environment variables)
# Removed: OUTPUT_DIR = "data" (Output is now to Blob Storage via __init__.py)

# Default values for placeholder data
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
    # Filter resources by 'email' tag presence
    resources = client.resources.list(filter="tagName eq 'email'")
    email_map = {}
    for res in resources:
        email = res.tags.get("email") if res.tags else None
        if email:
            # Store resource ID (lowercase for consistency) and associated email
            email_map[res.id.lower()] = email
    return email_map

def fetch_usage_details(subscription_id):
    """
    Fetches Azure consumption usage details for the last 7 days.
    Filters for Reserved Instance usage.
    """
    credential = DefaultAzureCredential()
    client = ConsumptionManagementClient(credential, subscription_id)
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=7) # Fetch data for the last 7 days

    usage_map = {}
    # Query usage details, filtering by 'Reservation' usage type (adjust as needed)
    # The 'properties' of usage details can vary; adapt access based on actual API response.
    # Note: 'metric' and 'resourceGroup' are examples; check actual JSON output from Consumption API.
    try:
        # Use a generator for potentially large results
        for usage in client.usage_details.list(
            scope=f"/subscriptions/{subscription_id}",
            expand="meterDetails,additionalInfo", # Expand for more details like RI name, SKU
            filter=f"properties/usageStart ge '{start_date.isoformat()}' and properties/usageEnd le '{end_date.isoformat()}'",
            metric="ActualCost" # Or 'AmortizedCost' depending on your reporting needs
        ):
            # Extract relevant info. Adapt these paths based on actual usage detail object structure.
            ri_id = usage.properties.get("instanceId", usage.properties.get("resourceId", "unknown_ri"))
            quantity = usage.properties.get("quantity", 0) # e.g., hours used
            usage_date = usage.properties.get("usageStart", datetime.utcnow().isoformat())
            sku = usage.properties.get("meterDetails", {}).get("meterName", "unknown_sku")
            region = usage.properties.get("resourceLocation", "unknown_region")

            if ri_id not in usage_map:
                usage_map[ri_id] = []

            usage_map[ri_id].append({
                "date": datetime.fromisoformat(usage_date.replace('Z', '+00:00')).date(), # Convert to date object
                "quantity": quantity,
                "sku": sku,
                "region": region
            })
    except Exception as e:
        print(f"[❌] Error fetching usage details for subscription {subscription_id}: {e}")
        # Depending on criticality, you might re-raise or return empty.
        # For a function, it's often better to raise to ensure the pipeline stops on critical errors.
        raise

    return usage_map
