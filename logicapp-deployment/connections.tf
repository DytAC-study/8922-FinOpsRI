resource "azurerm_api_connection" "outlook" {
  name                = "outlook"
  resource_group_name = var.resource_group
  location            = var.location

  managed_api_id = "/providers/Microsoft.Web/locations/${var.location}/managedApis/outlook"
  parameter_values = {
    "token:clientId"     = "<YOUR_CLIENT_ID>"
    "token:clientSecret" = "<YOUR_CLIENT_SECRET>"
    "token:tenantId"     = "<YOUR_TENANT_ID>"
  }
}
