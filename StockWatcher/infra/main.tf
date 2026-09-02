# StockWatcher infrastructure.
#
# A Container Apps *Job* on a cron schedule, deliberately not a VM: the job
# scales to zero between runs, so an hourly ~35-second scan costs cents rather
# than paying for an always-on machine.
#
#   cd infra
#   terraform init
#   terraform apply
#
# Or just run scripts/deploy.sh, which also builds and pushes the image.
#
# The WhatsApp channel on the Communication Services resource must be connected
# by hand afterwards - it needs an interactive Meta OAuth consent that has no
# ARM (and therefore no Terraform) equivalent.  See docs/whatsapp-template.md.

locals {
  # ACR and storage account names must be globally unique and allow no
  # hyphens, hence the stripped name plus a stable random suffix.  The name is
  # truncated rather than the suffix, so uniqueness survives a long var.name.
  bare_name = replace(var.name, "-", "")
  suffix    = random_string.suffix.result

  # Storage accounts: 3-24 chars.  "st" + 6-char suffix leaves 16 for the name.
  storage_name = "${substr(local.bare_name, 0, 16)}st${local.suffix}"
  # Registries: 5-50 chars, so var.name's own 17-char cap is already enough.
  registry_name = "${local.bare_name}${local.suffix}"

  table_name = "stockwatcher"

  acs_connection_string = (
    var.acs_connection_string != ""
    ? var.acs_connection_string
    : (var.create_communication_service
      ? azurerm_communication_service.this[0].primary_connection_string
    : "")
  )

  image = "${azurerm_container_registry.this.login_server}/${var.name}:${var.image_tag}"
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}

# --------------------------------------------------------------- observability

resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.name}-logs"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  # 30 days is plenty of history to answer "did it actually run last night?".
  retention_in_days = var.log_retention_days
}

# --------------------------------------------------------------------- registry

resource "azurerm_container_registry" "this" {
  name                = local.registry_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Basic"
  # Not needed: `az acr build` and `az acr login` authenticate with the caller's
  # AAD token, and the job pulls with its managed identity via AcrPull below.
  admin_enabled = false
}

# ---------------------------------------------------------------------- storage

resource "azurerm_storage_account" "this" {
  name                     = local.storage_name
  location                 = azurerm_resource_group.this.location
  resource_group_name      = azurerm_resource_group.this.name
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true
}

# Holds both the availability state and the discovered-store registry.  Table
# storage rather than a database because the access pattern is a single
# partition-key lookup per run.
resource "azurerm_storage_table" "state" {
  name = local.table_name
  # storage_account_name is deprecated and goes away in azurerm 5.0.
  storage_account_id = azurerm_storage_account.this.id
}

# -------------------------------------------------------------------- messaging

resource "azurerm_communication_service" "this" {
  count = var.create_communication_service ? 1 : 0

  name                = "${var.name}-acs"
  resource_group_name = azurerm_resource_group.this.name
  data_location       = var.communication_data_location
}

# --------------------------------------------------------------------- identity

resource "azurerm_user_assigned_identity" "this" {
  name                = "${var.name}-id"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

# Lets the job reach Table Storage with its managed identity instead of a
# connection-string secret.
resource "azurerm_role_assignment" "table_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

# --------------------------------------------------------------- container apps

resource "azurerm_container_app_environment" "this" {
  name                       = "${var.name}-env"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
}

resource "azurerm_container_app_job" "this" {
  name                         = "${var.name}-job"
  location                     = azurerm_resource_group.this.location
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id

  replica_timeout_in_seconds = var.replica_timeout_in_seconds
  # A scan is idempotent, but a retry storm would burn WhatsApp messages, so a
  # failed run waits for the next scheduled one instead.
  replica_retry_limit = 0

  schedule_trigger_config {
    cron_expression          = var.cron_expression
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.this.id
  }

  dynamic "secret" {
    for_each = local.acs_connection_string != "" ? [local.acs_connection_string] : []
    content {
      name  = "acs-connection-string"
      value = secret.value
    }
  }

  dynamic "secret" {
    for_each = var.search_api_key != "" ? [var.search_api_key] : []
    content {
      name  = "search-api-key"
      value = secret.value
    }
  }

  template {
    container {
      name   = var.name
      image  = local.image
      cpu    = var.cpu
      memory = var.memory

      env {
        name  = "STOCKWATCHER_STATE_BACKEND"
        value = "azure_table"
      }
      env {
        name  = "AZURE_TABLE_NAME"
        value = azurerm_storage_table.state.name
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = azurerm_storage_account.this.primary_table_endpoint
      }
      # DefaultAzureCredential needs this to pick the *user-assigned* identity;
      # without it the job falls back to the system identity and gets 403.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.this.client_id
      }

      env {
        name  = "ACS_CHANNEL_REGISTRATION_ID"
        value = var.whatsapp_channel_registration_id
      }
      env {
        name  = "WHATSAPP_TO"
        value = var.whatsapp_to
      }
      env {
        name  = "WHATSAPP_TEMPLATE_NAME"
        value = var.whatsapp_template_name
      }
      env {
        name  = "WHATSAPP_TEMPLATE_LANG"
        value = var.whatsapp_template_lang
      }
      env {
        name  = "STOCKWATCHER_SEARCH_BACKEND"
        value = var.search_backend
      }

      dynamic "env" {
        for_each = local.acs_connection_string != "" ? [1] : []
        content {
          name        = "ACS_CONNECTION_STRING"
          secret_name = "acs-connection-string"
        }
      }

      dynamic "env" {
        for_each = var.search_api_key != "" ? [var.search_backend] : []
        content {
          # The provider-specific variable the app reads depends on the backend.
          name = lookup({
            brave   = "BRAVE_SEARCH_API_KEY"
            bing    = "BING_SEARCH_API_KEY"
            serpapi = "SERPAPI_API_KEY"
          }, env.value, "BRAVE_SEARCH_API_KEY")
          secret_name = "search-api-key"
        }
      }
    }
  }

  # Without this the job can be created before it is allowed to pull, and the
  # first scheduled execution fails with an image-pull error.
  depends_on = [azurerm_role_assignment.acr_pull]
}
