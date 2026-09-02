output "resource_group_name" {
  description = "Resource group holding everything."
  value       = azurerm_resource_group.this.name
}

output "registry_name" {
  description = "ACR name, used by `az acr build`."
  value       = azurerm_container_registry.this.name
}

output "registry_login_server" {
  description = "ACR login server, the image prefix."
  value       = azurerm_container_registry.this.login_server
}

output "image" {
  description = "Fully qualified image reference the job is pointing at."
  value       = local.image
}

output "job_name" {
  description = "Container Apps Job name."
  value       = azurerm_container_app_job.this.name
}

output "storage_account_name" {
  description = "Storage account holding the state table."
  value       = azurerm_storage_account.this.name
}

output "table_name" {
  description = "Table holding availability state and the store registry."
  value       = azurerm_storage_table.state.name
}

output "communication_service_name" {
  description = "Communication Services resource, or empty when using an existing one."
  value = (
    var.create_communication_service
    ? azurerm_communication_service.this[0].name
    : ""
  )
}

output "log_analytics_workspace" {
  description = "Log Analytics workspace receiving the job's stdout."
  value       = azurerm_log_analytics_workspace.this.name
}

output "run_now_command" {
  description = "Trigger a run immediately instead of waiting for the cron."
  value = join(" ", [
    "az containerapp job start",
    "-g ${azurerm_resource_group.this.name}",
    "-n ${azurerm_container_app_job.this.name}",
  ])
}
