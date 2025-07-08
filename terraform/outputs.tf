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