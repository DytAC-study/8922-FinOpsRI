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

# Storage Queue for Function App Inter-communication (import_to_db_func -> analyze_ri_func)
resource "azurerm_storage_queue" "finops_ri_analysis_queue" {
  name                 = "finops-ri-analysis-queue"
  storage_account_name = azurerm_storage_account.main.name
}

# Azure Log Analytics Workspace for Application Insights logs
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name_prefix}-loganalytics-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018" # Recommended SKU for typical use cases
  retention_in_days   = 30          # Log retention in days, adjust as needed
  tags                = local.common_tags
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = "${local.name_prefix}-appins-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id # Link to Log Analytics Workspace
  tags                = local.common_tags
}

# App Service Plan (Consumption Plan for Function App)
resource "azurerm_service_plan" "main" {
  name                = "${local.name_prefix}-plan-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_plan_sku
  tags                = local.common_tags
}

# Function App
resource "azurerm_linux_function_app" "main" {
  name                        = "${local.name_prefix}-func-${local.suffix}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  service_plan_id             = azurerm_service_plan.main.id
  storage_account_name        = azurerm_storage_account.main.name
  storage_account_access_key  = azurerm_storage_account.main.primary_access_key
  functions_extension_version = "~4"

  site_config {
    application_stack {
      python_version = var.python_version
    }
  }

  identity {
    type = "SystemAssigned"
  }

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"            = "python"
    "AzureWebJobsStorage"                 = azurerm_storage_account.main.primary_connection_string
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "APPINSIGHTS_INSTRUMENTATIONKEY"      = azurerm_application_insights.main.instrumentation_key

    # Direct DB connection string
    "DATABASE_CONNECTION_STRING" = "Host=${azurerm_postgresql_flexible_server.main.name}.postgres.database.azure.com;Database=${azurerm_postgresql_flexible_server_database.main.name};Username=${var.postgresql_admin_username};Password=${var.postgresql_admin_password};SslMode=Require;"

    "EMAIL_METHOD" = var.email_method
    # REMOVED: SMTP settings are no longer needed as per code changes
    # "SMTP_HOST"   = var.email_method == "smtp" ? var.smtp_host : null
    # "SMTP_PORT"   = var.smtp_port
    # "SMTP_USER"   = var.email_method == "smtp" ? var.smtp_user : null
    # "SMTP_PASS"   = var.email_method == "smtp" ? var.smtp_pass : null
    # "SMTP_SENDER" = var.smtp_sender # This variable is still used for Logic App sender, keep it if needed there

    # Direct Logic App endpoint
    "LOGICAPP_ENDPOINT" = var.email_method == "logicapp" ? var.logicapp_endpoint : null

    "MIN_UTILIZATION_THRESHOLD"    = var.min_utilization_threshold
    "EXPIRY_WARNING_DAYS"          = var.expiry_warning_days
    "ANALYSIS_WINDOW_DAYS"         = var.analysis_window_days
    "UNDERUTILIZED_DAYS_THRESHOLD" = var.underutilized_days_threshold
    "UNUSED_DAYS_THRESHOLD"        = var.unused_days_threshold
    "DEFAULT_REGION"               = var.default_region
    "DEFAULT_SKU"                  = var.default_sku

    "RECIPIENT_EMAIL" = var.recipient_email
  }
  tags = local.common_tags
}

# Azure Database for PostgreSQL Flexible Server
resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "${local.name_prefix}-pgsql-${local.suffix}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "13"
  sku_name                      = var.postgresql_sku_name
  storage_mb                    = var.postgresql_storage_mb
  delegated_subnet_id           = null
  public_network_access_enabled = true

  administrator_login    = var.postgresql_admin_username
  administrator_password = var.postgresql_admin_password

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false
  tags = local.common_tags
}

# PostgreSQL Database
resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "ri_finops_db"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
}

# Null resource to create the 'ri_usage' table in PostgreSQL
resource "null_resource" "create_ri_usage_table" {
  depends_on = [azurerm_postgresql_flexible_server_database.main]
  # This resource is commented out as you prefer to manage tables manually for now.
  # If you wish Terraform to create this table, uncomment the provisioner block.
}

# PostgreSQL Firewall Rule
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_specific_ips" {
  for_each         = toset(var.allowed_ip_addresses)
  name             = "AllowIP-${replace(each.key, ".", "-")}"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = each.key
  end_ip_address   = each.key
}

# Azure Key Vault (Keeping the Key Vault resource as it might be used for other purposes,
# but removing the secrets related to DB and email from here).
resource "azurerm_key_vault" "main" {
  name                        = "finopsrikv${local.suffix}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  sku_name                    = "standard"
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  enabled_for_disk_encryption = false
  purge_protection_enabled    = false # Enable in production
  soft_delete_retention_days  = 7     # Increase in production

  access_policy {
    tenant_id               = data.azurerm_client_config.current.tenant_id
    object_id               = data.azurerm_client_config.current.object_id
    key_permissions         = []
    secret_permissions      = ["Get", "List", "Set", "Delete"] # Allow setting/getting secrets
    certificate_permissions = []
  }

  tags = local.common_tags
}

data "azurerm_client_config" "current" {}

# Assign Managed Identity permissions (removed KV access role, as no secrets are being read by func app for DB/email)
# If Key Vault is still intended for other secrets read by the Function App,
# you might need to re-add 'azurerm_role_assignment.func_app_kv_access' after confirming.
/*
resource "azurerm_role_assignment" "func_app_kv_access" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}
*/

resource "azurerm_role_assignment" "func_app_storage_blob_data_reader" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "func_app_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "func_app_storage_queue_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_resource_group_template_deployment" "email_sender_arm" {
  count               = var.email_method == "logicapp" ? 1 : 0
  name                = "${local.name_prefix}-logicapp-deployment-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  deployment_mode     = "Incremental"

  template_content = file("logicapp_template.json")

  parameters_content = jsonencode({
    logicAppName = {
      value = "${local.name_prefix}-logicapp-${local.suffix}"
    }
    location = {
      value = azurerm_resource_group.main.location
    }
  })
}
