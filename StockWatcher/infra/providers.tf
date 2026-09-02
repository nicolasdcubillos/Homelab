# Provider configuration.
#
# The azurerm version is pinned to a minor range: `azurerm_container_app_job`
# is a relatively young resource and its schema has moved between releases, so
# an unpinned provider is a good way to have a working config break later.

terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  # subscription_id comes from ARM_SUBSCRIPTION_ID or `az account set`.
  subscription_id = var.subscription_id != "" ? var.subscription_id : null

  features {
    resource_group {
      # Refuse to silently delete a resource group that still holds resources
      # Terraform does not know about.
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "random" {}
