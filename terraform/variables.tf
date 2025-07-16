variable "resource_group_name" {
  description = "The name of the resource group to create."
  type        = string
  default     = "rg-finops-ri-reporting"
}

variable "location" {
  description = "The Azure region where resources will be deployed."
  type        = string
  default     = "East US"
}

variable "environment" {
  description = "The deployment environment (e.g., dev, test, prod)."
  type        = string
  default     = "dev"
}

variable "unique_suffix" {
  description = "A unique suffix for resource names to ensure global uniqueness. Will be generated if not provided."
  type        = string
  default     = "" # Set in terraform.tfvars or allow random generation
}

variable "app_service_plan_sku" {
  description = "The SKU for the Azure App Service Plan (e.g., Y1, S1, B1, P1v2)."
  type        = string
  default     = "Y1" # Y1 is Free tier for Linux/Consumption (Serverless)
}

variable "app_service_plan_kind" {
  description = "The Kind for the Azure App Service Plan (e.g., Linux, Windows, FunctionApp)."
  type        = string
  default     = "FunctionApp" # Consumption plan kind
}

variable "python_version" {
  description = "The Python version for the Function App."
  type        = string
  default     = "3.9" # Recommended Python version for Azure Functions
}

variable "postgresql_sku_name" {
  description = "The SKU name for Azure Database for PostgreSQL Flexible Server."
  type        = string
  default     = "Standard_B1ms" # Burstable B1ms is cost-effective for dev/test
  # For production, consider General Purpose or Memory Optimized tiers like "Standard_D2s_v3"
}

variable "postgresql_storage_mb" {
  description = "The storage size in MB for Azure Database for PostgreSQL Flexible Server."
  type        = number
  default     = 20480 # 20 GB
}

variable "postgresql_admin_username" {
  description = "The administrator username for the PostgreSQL Flexible Server."
  type        = string
  default     = "riadmin"
}

variable "postgresql_admin_password" {
  description = "The administrator password for the PostgreSQL Flexible Server."
  type        = string
  sensitive   = true # Mark as sensitive so it's not shown in logs
}

variable "allowed_ip_addresses" {
  description = "A list of IP addresses or CIDR ranges allowed to connect to PostgreSQL. Use '0.0.0.0' for public access (LESS SECURE) or your local public IP."
  type        = list(string)
  default     = ["0.0.0.0"] # WARNING: 0.0.0.0 allows all public IPs. Restrict this in production.
}

variable "blob_container_names" {
  description = "List of Azure Blob Storage container names to create."
  type        = list(string)
  default = [
    "ri-usage-raw",       # For raw RI usage JSONs
    "ri-analysis-output", # For processed analysis JSONs
    "ri-email-reports"    # For generated HTML/CSV email reports
  ]
}

variable "email_method" {
  description = "Method for sending emails: 'logicapp' or 'smtp'."
  type        = string
  default     = "logicapp" # Using Logic App for flexibility and less secret management
}

variable "recipient_email" {
  description = "Email address to send RI analysis reports to."
  type        = string
}

variable "smtp_host" {
  description = "SMTP host if email_method is 'smtp'."
  type        = string
  default     = ""
}

variable "smtp_port" {
  description = "SMTP port if email_method is 'smtp'."
  type        = number
  default     = 587
}

variable "smtp_user" {
  description = "SMTP username if email_method is 'smtp'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "smtp_pass" {
  description = "SMTP password if email_method is 'smtp'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "smtp_sender" {
  description = "Sender email address if email_method is 'smtp'."
  type        = string
  default     = "no-reply@example.com"
}

variable "logicapp_endpoint" {
  description = "HTTP POST endpoint for Azure Logic App for email notifications if email_method is 'logicapp'."
  type        = string
  default     = "" # IMPORTANT: You will need to populate this in your terraform.tfvars if using logicapp
}

# Application Settings Thresholds
variable "min_utilization_threshold" {
  description = "Minimum utilization percentage for 'healthy' status."
  type        = number
  default     = 60
}

variable "expiry_warning_days" {
  description = "Number of days before expiry to trigger a warning."
  type        = number
  default     = 30
}

variable "analysis_window_days" {
  description = "Number of past days to consider for utilization analysis."
  type        = number
  default     = 7
}

variable "underutilized_days_threshold" {
  description = "Days of underutilization to trigger an alert."
  type        = number
  default     = 3
}

variable "unused_days_threshold" {
  description = "Days of non-usage to trigger an alert."
  type        = number
  default     = 3
}

variable "default_region" {
  description = "Default region to use if not found in data."
  type        = string
  default     = "eastus"
}

variable "default_sku" {
  description = "Default SKU to use if not found in data."
  type        = string
  default     = "Standard_DS1_v2"
}