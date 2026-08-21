targetScope = 'subscription'

param location string = 'eastus'
param environment string = 'dev'
param projectName string = 'agent-router'
param principalId string

var resourceGroupName = '${projectName}-${environment}-rg'
var foundryName = replace('${projectName}-${environment}-foundry', '-', '')
var foundryProjectName = '${foundryName}-proj'
var searchServiceName = replace('${projectName}-${environment}-search', '-', '')
var acrName = replace('${projectName}${environment}acr', '-', '')
var appInsightsName = '${projectName}-${environment}-ai'
var logAnalyticsName = '${projectName}-${environment}-law'

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
}

module monitoring 'modules/monitoring.bicep' = {
  scope: resourceGroup
  name: 'monitoring'
  params: {
    location: location
    logAnalyticsName: logAnalyticsName
    appInsightsName: appInsightsName
  }
}

module search 'modules/search.bicep' = {
  scope: resourceGroup
  name: 'search'
  params: {
    location: location
    searchServiceName: searchServiceName
    principalId: principalId
  }
}

module foundry 'modules/foundry.bicep' = {
  scope: resourceGroup
  name: 'foundry'
  params: {
    location: location
    foundryName: foundryName
    foundryProjectName: foundryProjectName
    principalId: principalId
  }
}

module acr 'modules/acr.bicep' = {
  scope: resourceGroup
  name: 'acr'
  params: {
    location: location
    acrName: acrName
  }
}

output resourceGroupName string = resourceGroup.name
output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output foundryEndpoint string = foundry.outputs.foundryEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output openaiEndpoint string = foundry.outputs.foundryEndpoint
output acrLoginServer string = acr.outputs.loginServer
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
