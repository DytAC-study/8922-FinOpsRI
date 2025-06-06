resource "azurerm_logic_app_workflow" "email_logic" {
  name                = var.logicapp_name
  location            = var.location
  resource_group_name = var.resource_group

  definition = jsondecode(file("logicapp-definition.json"))
}
