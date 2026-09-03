output "vm_public_ip" {
  description = "Public IP address of the VM."
  value       = azurerm_public_ip.this.ip_address
}

output "vm_name" {
  description = "Name of the VM."
  value       = azurerm_linux_virtual_machine.this.name
}

output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint (set as AZURE_OPENAI_ENDPOINT)."
  value       = azurerm_cognitive_account.openai.endpoint
}

output "openai_primary_key" {
  description = "Azure OpenAI primary key (set as AZURE_OPENAI_API_KEY)."
  value       = azurerm_cognitive_account.openai.primary_access_key
  sensitive   = true
}

output "openai_triage_deployment" {
  value = azurerm_cognitive_deployment.triage.name
}

output "openai_analysis_deployment" {
  value = azurerm_cognitive_deployment.analysis.name
}

output "acs_connection_string" {
  description = "Communication Services connection string (set as ACS_CONNECTION_STRING). Empty if create_communication_service = false."
  value       = var.create_communication_service ? azurerm_communication_service.this[0].primary_connection_string : ""
  sensitive   = true
}
