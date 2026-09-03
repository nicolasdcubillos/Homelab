# Generic homelab-style infrastructure: one small Linux VM (cron-driven) plus
# the Azure OpenAI and Communication Services resources PortfolioWatcher
# needs. Resource names are deliberately generic (var.project_name, default
# "homelab") because this VM is meant to host more personal services over
# time -- PortfolioWatcher's own code lives in its own subdirectory on the VM
# (/opt/services/portfoliowatcher/), and only its systemd timers keep
# service-specific names.
#
#   cd infra
#   terraform init
#   terraform plan
#   terraform apply
#
# Requires `az login` first. See scripts/bootstrap_vm.sh and scripts/deploy.sh
# for the steps that follow `terraform apply` (installing Python, syncing
# code, and enabling the systemd timers).

locals {
  resource_group_name = var.resource_group_name != "" ? var.resource_group_name : "${var.project_name}-rg"
  suffix              = random_string.suffix.result
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.location
  tags     = var.tags
}

# ------------------------------------------------------------------- network

resource "azurerm_virtual_network" "this" {
  name                = "${var.project_name}-vnet"
  address_space       = ["10.10.0.0/16"]
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

resource "azurerm_subnet" "this" {
  name                 = "${var.project_name}-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.10.1.0/24"]
}

resource "azurerm_network_security_group" "this" {
  name                = "${var.project_name}-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags

  # SSH restricted to the caller-supplied address. Setting
  # allowed_ssh_source_address = "*" opens SSH to the whole internet -- only
  # do that temporarily and tighten it right after initial setup.
  security_rule {
    name                       = "AllowSSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.allowed_ssh_source_address
    destination_address_prefix = "*"
  }
}

resource "azurerm_public_ip" "this" {
  name                = "${var.project_name}-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_interface" "this" {
  name                = "${var.project_name}-nic"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.this.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.this.id
  }
}

resource "azurerm_network_interface_security_group_association" "this" {
  network_interface_id      = azurerm_network_interface.this.id
  network_security_group_id = azurerm_network_security_group.this.id
}

# ----------------------------------------------------------------------- VM

resource "azurerm_linux_virtual_machine" "this" {
  name                  = "${var.project_name}-vm"
  location              = azurerm_resource_group.this.location
  resource_group_name   = azurerm_resource_group.this.name
  size                  = var.vm_size
  admin_username        = var.admin_username
  network_interface_ids = [azurerm_network_interface.this.id]
  tags                  = var.tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  disable_password_authentication = true
}

# ---------------------------------------------------------------- Azure OpenAI

resource "azurerm_cognitive_account" "openai" {
  name                  = "${var.project_name}-openai-${local.suffix}"
  location              = azurerm_resource_group.this.location
  resource_group_name   = azurerm_resource_group.this.name
  kind                  = "OpenAI"
  sku_name              = var.openai_sku_name
  custom_subdomain_name = "${var.project_name}-openai-${local.suffix}"
  tags                  = var.tags
}

# Tier 1: cheap "triage" deployment, discards noise from raw news items.
resource "azurerm_cognitive_deployment" "triage" {
  name                 = var.openai_triage_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_triage_model
    version = var.openai_triage_model_version
  }

  scale {
    type     = "GlobalStandard"
    capacity = var.openai_deployment_capacity
  }
}

# Tier 2: capable "analysis" deployment, classifies risk/opportunity signals
# and drafts the weekly portfolio report.
resource "azurerm_cognitive_deployment" "analysis" {
  name                 = var.openai_analysis_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_analysis_model
    version = var.openai_analysis_model_version
  }

  scale {
    type     = "GlobalStandard"
    capacity = var.openai_deployment_capacity
  }
}

# ---------------------------------------------------------- Communication Services

# WhatsApp channel must be connected by hand afterwards -- it needs an
# interactive Meta OAuth consent that has no ARM/Terraform equivalent. See
# docs/architecture.md.
resource "azurerm_communication_service" "this" {
  count               = var.create_communication_service ? 1 : 0
  name                = "${var.project_name}-acs-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  data_location       = var.acs_data_location
  tags                = var.tags
}
