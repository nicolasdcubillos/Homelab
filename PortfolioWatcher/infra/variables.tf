variable "project_name" {
  description = <<-EOT
    Generic, non-descriptive name for this infrastructure project (used as a
    prefix for the resource group, VM, NSG, etc.). Intentionally NOT named
    after PortfolioWatcher: the same VM is meant to host more personal
    services over time. PortfolioWatcher's own code/config lives in its own
    subdirectory on the VM (/opt/services/portfoliowatcher/) and its systemd
    timers keep their specific names regardless of this variable.
  EOT
  type        = string
  default     = "homelab"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group name. Defaults to '<project_name>-rg'."
  type        = string
  default     = ""
}

variable "admin_username" {
  description = "Linux admin username for the VM."
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key" {
  description = "Public SSH key (contents of e.g. ~/.ssh/id_ed25519.pub) used to log into the VM."
  type        = string
}

variable "allowed_ssh_source_address" {
  description = <<-EOT
    Source address prefix allowed to reach port 22 on the NSG, e.g. your
    public IP in CIDR form ("203.0.113.10/32"). Set to "*" to allow SSH from
    anywhere -- NOT recommended, only use temporarily and tighten it after
    setup. There is no default on purpose: you must make this choice
    explicitly.
  EOT
  type        = string
}

variable "vm_size" {
  description = "VM size. B2s is the default requested: 2 vCPU / 4 GiB RAM, burstable, cheap."
  type        = string
  default     = "Standard_B2s"
}

variable "os_disk_size_gb" {
  description = "OS disk size in GiB."
  type        = number
  default     = 30
}

variable "openai_sku_name" {
  description = "SKU for the Azure OpenAI (Cognitive Services) account."
  type        = string
  default     = "S0"
}

variable "openai_triage_deployment_name" {
  description = "Azure OpenAI deployment name for the cheap 'triage' tier (Azure resource identifier, independent of the underlying model)."
  type        = string
  default     = "portfoliowatcher-triage"
}

variable "openai_triage_model" {
  description = "Model catalog name backing the cheap 'triage' deployment. Must have available quota in this region/subscription -- check with `az cognitiveservices usage list --location <region>`."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "openai_triage_model_version" {
  description = "Model version for the triage deployment (must match `az cognitiveservices account list-models` for this account/region)."
  type        = string
  default     = "2025-04-14"
}

variable "openai_analysis_deployment_name" {
  description = "Azure OpenAI deployment name for the capable 'analysis' tier (Azure resource identifier, independent of the underlying model)."
  type        = string
  default     = "portfoliowatcher-analysis"
}

variable "openai_analysis_model" {
  description = "Model catalog name backing the capable 'analysis' deployment. Must have available quota in this region/subscription -- check with `az cognitiveservices usage list --location <region>`."
  type        = string
  default     = "gpt-5-mini"
}

variable "openai_analysis_model_version" {
  description = "Model version for the analysis deployment (must match `az cognitiveservices account list-models` for this account/region)."
  type        = string
  default     = "2025-08-07"
}

variable "openai_deployment_capacity" {
  description = "Tokens-per-minute capacity (in thousands) for each model deployment."
  type        = number
  default     = 10
}

variable "create_communication_service" {
  description = "Whether to create a new Azure Communication Services resource for WhatsApp."
  type        = bool
  default     = true
}

variable "acs_data_location" {
  description = "Data location for the Communication Services resource."
  type        = string
  default     = "United States"
}

variable "tags" {
  description = "Common tags applied to every resource."
  type        = map(string)
  default = {
    managed_by = "terraform"
  }
}
