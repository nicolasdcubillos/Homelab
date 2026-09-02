variable "subscription_id" {
  description = "Azure subscription id. Leave empty to use ARM_SUBSCRIPTION_ID or the az CLI's current subscription."
  type        = string
  default     = ""
}

variable "name" {
  description = "Base name for all resources."
  type        = string
  default     = "stockwatcher"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,16}$", var.name))
    error_message = "name must be 3-17 chars, lowercase alphanumeric or hyphen, starting with a letter."
  }
}

variable "resource_group_name" {
  description = "Resource group to create and hold everything."
  type        = string
  default     = "stockwatcher-rg"
}

variable "location" {
  description = "Azure region for all regional resources."
  type        = string
  default     = "eastus"
}

variable "cron_expression" {
  description = "Scan schedule in UTC. Default: hourly on the hour."
  type        = string
  default     = "0 * * * *"
}

variable "image_tag" {
  description = "Container image tag to run. scripts/deploy.sh sets this per deploy."
  type        = string
  default     = "latest"
}

# ------------------------------------------------------------------- compute

variable "cpu" {
  description = "CPU cores for the job. 1.0 is comfortable for headless chromium."
  type        = number
  default     = 1.0
}

variable "memory" {
  description = "Memory for the job. Chromium needs ~2Gi of headroom."
  type        = string
  default     = "2Gi"
}

variable "replica_timeout_in_seconds" {
  description = "Seconds before a stuck run is killed."
  type        = number
  default     = 900
}

variable "log_retention_days" {
  description = "Log Analytics retention. The job logs one summary line per run."
  type        = number
  default     = 30
}

# ------------------------------------------------------------------ messaging

variable "create_communication_service" {
  description = <<-EOT
    Create the Communication Services resource. Set to false if you already
    made one by hand (for example because the WhatsApp channel is already
    connected to it) and pass its connection string in acs_connection_string.
  EOT
  type        = bool
  default     = true
}

variable "communication_data_location" {
  description = "Data residency for Communication Services."
  type        = string
  default     = "United States"

  validation {
    condition = contains(
      ["United States", "Europe", "Asia Pacific", "Australia", "UK", "Canada"],
      var.communication_data_location
    )
    error_message = "Unsupported data location."
  }
}

variable "acs_connection_string" {
  description = <<-EOT
    Overrides the created Communication Services connection string. Required
    when create_communication_service is false. Keep it out of version
    control: pass it with TF_VAR_acs_connection_string rather than tfvars.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "whatsapp_channel_registration_id" {
  description = "WhatsApp channel GUID. Empty until the channel is connected in the portal."
  type        = string
  default     = ""
}

variable "whatsapp_to" {
  description = "Destination number(s) in E.164, comma-separated. e.g. +573001234567"
  type        = string
  default     = ""
}

variable "whatsapp_template_name" {
  description = "Approved Meta template name."
  type        = string
  default     = "stockwatcher_restock"
}

variable "whatsapp_template_lang" {
  description = "Template language code. Must match what was registered with Meta."
  type        = string
  default     = "es"
}

# ------------------------------------------------------------------ discovery

variable "search_backend" {
  description = "Store auto-discovery search backend: brave, bing, serpapi, auto or none."
  type        = string
  default     = "none"
}

variable "search_api_key" {
  description = "API key for the search backend. Empty leaves discovery a no-op."
  type        = string
  default     = ""
  sensitive   = true
}
