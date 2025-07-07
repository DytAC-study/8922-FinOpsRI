output "resource_group_name" {
  description = "Name of the deployed Resource Group."
  value       = azurerm_resource_group.main.name
}

output "function_app_name" {
  description = "Name of the deployed Azure Function App."
  value       = azurerm_linux_function_app.main.name
}

output "function_app_default_hostname" {
  description = "Default hostname of the deployed Azure Function App."
  value       = azurerm_linux_function_app.main.default_hostname
}

output "storage_account_name" {
  description = "Name of the deployed Storage Account."
  value       = azurerm_storage_account.main.name
}

output "postgresql_flexible_server_fqdn" {
  description = "Fully Qualified Domain Name (FQDN) of the PostgreSQL Flexible Server."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "key_vault_uri" {
  description = "URI of the deployed Azure Key Vault."
  value       = azurerm_key_vault.main.vault_uri
}

output "db_connection_string_secret_id" {
  description = "Key Vault Secret ID for the PostgreSQL Connection String. Use this in your Function App settings."
  value       = azurerm_key_vault_secret.db_conn_string.id
  sensitive   = true
}

output "smtp_host_secret_id" {
  description = "Key Vault Secret ID for the SMTP Host (if applicable)."
  value       = var.email_method == "smtp" ? azurerm_key_vault_secret.smtp_host_secret[0].id : "N/A"
  sensitive   = true
}

output "logic_app_endpoint_secret_id" {
  description = "Key Vault Secret ID for the Logic App Endpoint (if applicable). Remember to update its value after Logic App deployment."
  value       = var.email_method == "logicapp" ? azurerm_key_vault_secret.logicapp_endpoint_secret[0].id : "N/A"
  sensitive   = true
}