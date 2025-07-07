# Generate a unique suffix if not provided
resource "random_string" "suffix" {
  count   = var.unique_suffix == "" ? 1 : 0
  length  = 8
  special = false
  upper   = false
  numeric = true
}

locals {
  name_prefix = "${var.resource_group_name}-${var.environment}"
  suffix      = var.unique_suffix == "" ? random_string.suffix[0].result : var.unique_suffix
  common_tags = {
    Environment = var.environment
    Project     = "FinOps RI Reporting"
    ManagedBy   = "Terraform"
  }
}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# Storage Account for Function App code, logs, and Blob Storage for data/reports
resource "azurerm_storage_account" "main" {
  # Shorten name to fit Azure's 3-24 char limit and only lowercase letters/numbers
  name                     = "finopsrisa${local.suffix}" # Example: finopsrisadyttest01 (16 chars)
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # Or "GRS" for geo-redundancy
  tags                     = local.common_tags
}

# Blob Containers
resource "azurerm_storage_container" "containers" {
  for_each              = toset(var.blob_container_names)
  name                  = each.key
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# >>>>>>>>>>>>>>>>>> HERE IS THE NEW QUEUE RESOURCE <<<<<<<<<<<<<<<<<<
# Storage Queue for Function App Inter-communication (import_to_db_func -> analyze_ri_func)
resource "azurerm_storage_queue" "finops_ri_analysis_queue" {
  name                 = "finops-ri-analysis-queue"
  storage_account_name = azurerm_storage_account.main.name # References the 'main' storage account defined above
}
# >>>>>>>>>>>>>>>>>> END OF NEW QUEUE RESOURCE <<<<<<<<<<<<<<<<<<


# Application Insights
resource "azurerm_application_insights" "main" {
  name                = "${local.name_prefix}-appins-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web" # Or "other"
  tags                = local.common_tags
}

# App Service Plan (Consumption Plan for Function App)
resource "azurerm_service_plan" "main" {
  name                = "${local.name_prefix}-plan-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux" # Azure Functions on Consumption plan require Linux
  sku_name            = var.app_service_plan_sku
  tags                = local.common_tags
}

# Function App
resource "azurerm_linux_function_app" "main" {
  name                      = "${local.name_prefix}-func-${local.suffix}"
  resource_group_name       = azurerm_resource_group.main.name
  location                  = azurerm_resource_group.main.location
  service_plan_id           = azurerm_service_plan.main.id
  storage_account_name        = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key
  functions_extension_version= "~4" # Use ~4 for Function App v4 runtime

  site_config {
    application_stack {
      python_version = var.python_version
    }
  }

  identity {
    type = "SystemAssigned" # Enable Managed Identity for accessing Key Vault, Storage, DB
  }

  app_settings = {
    # Azure Functions specific settings
    "FUNCTIONS_WORKER_RUNTIME"          = "python"
    "AzureWebJobsStorage"               = azurerm_storage_account.main.primary_connection_string
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false" # For consumption plans, content comes from storage
    "APPINSIGHTS_INSTRUMENTATIONKEY" = azurerm_application_insights.main.instrumentation_key

    # Database Connection String (retrieved from Key Vault)
    # This setting references a Key Vault secret. The Function App's Managed Identity
    # must have 'Get' permission on this secret.
    "DATABASE_CONNECTION_STRING" = format("@Microsoft.KeyVault(SecretUri=%s)", azurerm_key_vault_secret.db_conn_string.id)

    # Email Method and related settings (retrieved from Key Vault if sensitive)
    "EMAIL_METHOD" = var.email_method
    "SMTP_HOST"    = var.email_method == "smtp" ? format("@Microsoft.KeyVault(SecretUri=%s)", azurerm_key_vault_secret.smtp_host_secret[0].id) : null
    "SMTP_PORT"    = var.smtp_port # Port is not sensitive
    "SMTP_USER"    = var.email_method == "smtp" ? format("@Microsoft.KeyVault(SecretUri=%s)", azurerm_key_vault_secret.smtp_user_secret[0].id) : null
    "SMTP_PASS"    = var.email_method == "smtp" ? format("@Microsoft.KeyVault(SecretUri=%s)", azurerm_key_vault_secret.smtp_pass_secret[0].id) : null
    "SMTP_SENDER"  = var.smtp_sender

    # Logic App Endpoint (retrieved from Key Vault)
    "LOGICAPP_ENDPOINT" = var.email_method == "logicapp" ? format("@Microsoft.KeyVault(SecretUri=%s)", azurerm_key_vault_secret.logicapp_endpoint_secret[0].id) : null

    # Thresholds and Default values
    "MIN_UTILIZATION_THRESHOLD"    = var.min_utilization_threshold
    "EXPIRY_WARNING_DAYS"          = var.expiry_warning_days
    "ANALYSIS_WINDOW_DAYS"         = var.analysis_window_days
    "UNDERUTILIZED_DAYS_THRESHOLD" = var.underutilized_days_threshold
    "UNUSED_DAYS_THRESHOLD"        = var.unused_days_threshold
    "DEFAULT_REGION"               = var.default_region
    "DEFAULT_SKU"                  = var.default_sku

    # NEW: Add RECIPIENT_EMAIL for Function App settings
    "RECIPIENT_EMAIL" = var.recipient_email # This should be a new variable in your variables.tf
  }
  tags = local.common_tags
}


# Azure Database for PostgreSQL Flexible Server
resource "azurerm_postgresql_flexible_server" "main" {
  name                = "${local.name_prefix}-pgsql-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  version             = "13" # Or "14", "15"
  sku_name            = var.postgresql_sku_name # Will be updated in terraform.tfvars
  storage_mb          = var.postgresql_storage_mb # Will be updated in terraform.tfvars
  delegated_subnet_id = null # Using public access for simplicity, for VNET integration this would be a subnet ID
  public_network_access_enabled = true # Enable public access

  administrator_login    = var.postgresql_admin_username
  administrator_password = var.postgresql_admin_password

  backup_retention_days = 7
  geo_redundant_backup_enabled = false

  tags = local.common_tags
}

# PostgreSQL Database
resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "ri_finops_db"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
}

# PostgreSQL Firewall Rule (Allow Azure services and specified IPs)
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_specific_ips" {
  for_each          = toset(var.allowed_ip_addresses)
  name              = "AllowIP-${replace(each.key, ".", "-")}" # Name based on IP
  server_id         = azurerm_postgresql_flexible_server.main.id
  start_ip_address = each.key
  end_ip_address   = each.key
}


# Azure Key Vault
resource "azurerm_key_vault" "main" {
  # Shorten name to fit Azure's 3-24 char limit and allow alphanumeric/dashes
  name                  = "finopsrikv${local.suffix}" # Example: finopsrikvdyttest01 (16 chars)
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  sku_name              = "standard"
  tenant_id             = data.azurerm_client_config.current.tenant_id
  enabled_for_disk_encryption = false # Not relevant here
  purge_protection_enabled    = false # Enable in production
  soft_delete_retention_days  = 7    # Increase in production

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id # Your own user/service principal
    key_permissions = []
    secret_permissions = ["Get", "List", "Set", "Delete"] # Allow setting/getting secrets
    certificate_permissions = []
  }

  tags = local.common_tags
}

# Data source for current Azure client configuration (to get tenant_id and object_id)
data "azurerm_client_config" "current" {}


# Key Vault Secrets
# PostgreSQL Connection String Secret
resource "azurerm_key_vault_secret" "db_conn_string" {
  name         = "DbConnectionString"
  value        = "Host=${azurerm_postgresql_flexible_server.main.name}.postgres.database.azure.com;Database=${azurerm_postgresql_flexible_server_database.main.name};Username=${var.postgresql_admin_username};Password=${var.postgresql_admin_password};SslMode=Require;"
  key_vault_id = azurerm_key_vault.main.id
  content_type = "text/plain"
}

# SMTP Secrets (only created if email_method is 'smtp')
resource "azurerm_key_vault_secret" "smtp_host_secret" {
  count        = var.email_method == "smtp" ? 1 : 0
  name         = "SmtpHost"
  value        = var.smtp_host
  key_vault_id = azurerm_key_vault.main.id
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "smtp_user_secret" {
  count        = var.email_method == "smtp" ? 1 : 0
  name         = "SmtpUser"
  value        = var.smtp_user
  key_vault_id = azurerm_key_vault.main.id
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "smtp_pass_secret" {
  count        = var.email_method == "smtp" ? 1 : 0
  name         = "SmtpPass"
  value        = var.smtp_pass
  key_vault_id = azurerm_key_vault.main.id
  content_type = "text/plain"
}

# Logic App Endpoint Secret (only created if email_method is 'logicapp')
# Value will be updated manually after Logic App deployment or via separate step
resource "azurerm_key_vault_secret" "logicapp_endpoint_secret" {
  count        = var.email_method == "logicapp" ? 1 : 0
  name         = "LogicAppEndpoint"
  value        = "https://your-logic-app-http-trigger-url-goes-here" # Placeholder: Update this after Logic App creation
  key_vault_id = azurerm_key_vault.main.id
  content_type = "text/plain"
}


# Assign Managed Identity permissions
# Function App System Assigned Managed Identity
resource "azurerm_role_assignment" "func_app_kv_access" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User" # Allows 'Get' secrets
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "func_app_storage_blob_data_reader" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Reader" # For reading from 'ri-usage-raw' (implicitly, as Function App reads its code from storage too)
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "func_app_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor" # For writing to 'ri-analysis-output'
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

# NEW: Role assignment for Function App to access Storage Queue (Data Contributor)
resource "azurerm_role_assignment" "func_app_storage_queue_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Queue Data Contributor" # For sending/receiving messages to/from queue
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}


# Azure Logic App (Consumption) - HTTP Trigger for Email (via ARM Template Deployment)
# This replaces the direct azurerm_logic_app_workflow with workflow_definition
resource "azurerm_resource_group_template_deployment" "email_sender_arm" {
  count               = var.email_method == "logicapp" ? 1 : 0
  name                = "${local.name_prefix}-logicapp-deployment-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  deployment_mode     = "Incremental"

  template_content = file("logicapp_template.json") # 引用 ARM 模板文件

  parameters_content = jsonencode({
    logicAppName = {
      value = "${local.name_prefix}-logicapp-${local.suffix}"
    }
    location = {
      value = azurerm_resource_group.main.location
    }
  })
}