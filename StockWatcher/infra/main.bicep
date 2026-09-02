// StockWatcher infrastructure.
//
// A Container Apps *Job* on a cron schedule, deliberately not a VM: the job
// scales to zero between runs, so an hourly 40-second scan costs cents rather
// than paying for an always-on machine.
//
//   az deployment group create -g <rg> -f infra/main.bicep -p @infra/main.parameters.json
//
// The WhatsApp channel on the Communication Services resource must be
// connected by hand afterwards - it needs an interactive Meta OAuth consent
// that has no ARM equivalent.  See docs/whatsapp-template.md.

@description('Base name for all resources; must be globally unique-ish (3-17 chars).')
@minLength(3)
@maxLength(17)
param name string = 'stockwatcher'

@description('Location for all resources.')
param location string = resourceGroup().location

@description('Cron schedule for the scan, in UTC. Default: hourly on the hour.')
param cronExpression string = '0 * * * *'

@description('Container image to run. Set by scripts/deploy.sh after the ACR push.')
param imageTag string = 'latest'

@description('Data residency for the Communication Services resource.')
@allowed([
  'United States'
  'Europe'
  'Asia Pacific'
  'Australia'
  'UK'
  'Canada'
])
param communicationDataLocation string = 'United States'

@description('WhatsApp destination number in E.164, e.g. +573001234567.')
param whatsappTo string = ''

@description('Approved Meta template name.')
param whatsappTemplateName string = 'stockwatcher_restock'

@description('Template language code.')
param whatsappTemplateLang string = 'es'

@description('WhatsApp channel registration id (GUID). Empty until the channel is connected in the portal.')
param whatsappChannelRegistrationId string = ''

@description('CPU cores for the job. 1.0 is comfortable for headless chromium.')
param cpu string = '1.0'

@description('Memory for the job. Chromium needs ~2Gi headroom.')
param memory string = '2Gi'

@description('Minutes before a stuck run is killed.')
param replicaTimeoutSeconds int = 900

var uniqueSuffix = uniqueString(resourceGroup().id)
var registryName = toLower('${replace(name, '-', '')}${uniqueSuffix}')
var storageName = toLower('${replace(name, '-', '')}st${substring(uniqueSuffix, 0, 6)}')
var image = '${registry.properties.loginServer}/${name}:${imageTag}'

// ---------------------------------------------------------------- observability

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    // The job logs a one-line summary per run; 30 days is plenty of history
    // to answer "did it actually run last night?".
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------- registry

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  sku: { name: 'Basic' }
  properties: {
    // Admin user keeps scripts/deploy.sh to a single `az acr login`; the job
    // itself authenticates with its managed identity via AcrPull below.
    adminUserEnabled: true
  }
}

// ----------------------------------------------------------------------- storage

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// Holds both the seen/unseen availability state and the discovered-store
// registry.  Table storage is used rather than a database because the access
// pattern is a single partition key lookup per run.
resource stateTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'stockwatcher'
}

// ------------------------------------------------------------------ messaging

resource communication 'Microsoft.Communication/communicationServices@2023-06-01-preview' = {
  name: '${name}-acs'
  location: 'global'
  properties: {
    dataLocation: communicationDataLocation
  }
}

// ------------------------------------------------------------------- identity

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-id'
  location: location
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var tableContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Lets the job reach Table Storage with its managed identity instead of a
// connection-string secret.
resource tableContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, tableContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableContributorRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------ container apps

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: '${name}-job'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  dependsOn: [acrPull]
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: replicaTimeoutSeconds
      // A scan is idempotent, but a retry storm would burn WhatsApp messages,
      // so failures wait for the next scheduled run instead.
      replicaRetryLimit: 0
      scheduleTriggerConfig: {
        cronExpression: cronExpression
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'acs-connection-string'
          value: communication.listKeys().primaryConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            { name: 'STOCKWATCHER_STATE_BACKEND', value: 'azure_table' }
            { name: 'AZURE_TABLE_NAME', value: stateTable.name }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.table.${environment().suffixes.storage}' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'ACS_CONNECTION_STRING', secretRef: 'acs-connection-string' }
            { name: 'ACS_CHANNEL_REGISTRATION_ID', value: whatsappChannelRegistrationId }
            { name: 'WHATSAPP_TO', value: whatsappTo }
            { name: 'WHATSAPP_TEMPLATE_NAME', value: whatsappTemplateName }
            { name: 'WHATSAPP_TEMPLATE_LANG', value: whatsappTemplateLang }
          ]
        }
      ]
    }
  }
}

output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output jobName string = job.name
output storageAccountName string = storage.name
output communicationServiceName string = communication.name
output logAnalyticsWorkspace string = logs.name
