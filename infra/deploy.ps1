#!/usr/bin/env pwsh
<#
.SYNOPSIS
Deploy agent router demo infrastructure to Azure.

.DESCRIPTION
Creates resource group, Foundry project, AI Search, and OpenAI with embeddings+reasoning models.

.PARAMETER subscriptionId
Azure subscription ID. Defaults to current context.

.PARAMETER location
Azure region. Defaults to eastus.

.PARAMETER environment
Environment name (dev/staging/prod). Defaults to dev.

.EXAMPLE
./deploy.ps1 -subscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" -location "eastus"
#>

param(
  [string]$subscriptionId,
  [string]$location = 'eastus',
  [string]$environment = 'dev',
  [string]$projectName = 'agent-router'
)

$ErrorActionPreference = 'Stop'

function Invoke-AzCli {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI command failed with exit code $LASTEXITCODE"
  }
}

# Validate prerequisites
$requiredTools = @('az')
foreach ($tool in $requiredTools) {
  if (!(Get-Command $tool -ErrorAction SilentlyContinue)) {
    Write-Error "$tool not found. Install it and try again."
    exit 1
  }
}
az bicep version | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Error "Azure CLI Bicep support is not available. Run 'az bicep install' and try again."
  exit 1
}

# Set subscription
if ($subscriptionId) {
  Write-Host "Setting subscription: $subscriptionId"
  Invoke-AzCli { az account set --subscription $subscriptionId }
} else {
  $subscriptionId = az account show --query id -o tsv
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to read current Azure subscription."
  }
  Write-Host "Using current subscription: $subscriptionId"
}

# Derive resource names
$resourceGroupName = "$projectName-$environment-rg"
$templateFile = Join-Path $PSScriptRoot 'main.bicep'
$principalId = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0) {
  throw "Unable to resolve signed-in user object id."
}

if (!(Test-Path $templateFile)) {
  Write-Error "Template file not found: $templateFile"
  exit 1
}

Write-Host "Deploying to resource group: $resourceGroupName"
Write-Host "Location: $location"
Write-Host "Environment: $environment"
Write-Host "Principal ID: $principalId"

# Create resource group
Write-Host "Creating resource group..."
Invoke-AzCli { az group create --name $resourceGroupName --location $location }

# Deploy Bicep template
Write-Host "Deploying Bicep template..."
$deploymentName = "$projectName-$environment-$(Get-Date -Format 'yyyyMMddHHmmss')"
$deploymentJson = az deployment sub create `
  --name $deploymentName `
  --location $location `
  --template-file $templateFile `
  --parameters location=$location environment=$environment projectName=$projectName principalId=$principalId `
  --output json
if ($LASTEXITCODE -ne 0) {
  throw "Azure deployment failed."
}
$deployment = $deploymentJson | ConvertFrom-Json

Write-Host "Deployment succeeded."
Write-Host ""
Write-Host "=== Deployment Outputs ===" -ForegroundColor Green
Write-Host "Resource Group: $($deployment.properties.outputs.resourceGroupName.value)"
Write-Host "Foundry Project Endpoint: $($deployment.properties.outputs.foundryProjectEndpoint.value)"
Write-Host "AI Search Endpoint: $($deployment.properties.outputs.searchEndpoint.value)"
Write-Host "OpenAI Endpoint: $($deployment.properties.outputs.openaiEndpoint.value)"
Write-Host "ACR Login Server: $($deployment.properties.outputs.acrLoginServer.value)"
Write-Host "App Insights Connection String: $($deployment.properties.outputs.appInsightsConnectionString.value)"

# Store outputs for later use
$outputFile = Join-Path $PSScriptRoot '.deployment-outputs.json'
$deployment.properties.outputs | ConvertTo-Json | Set-Content $outputFile
Write-Host ""
Write-Host "Outputs saved to: $outputFile"

# Export environment variables
$env:AZURE_RESOURCE_GROUP = $resourceGroupName
$env:AZURE_SUBSCRIPTION_ID = $subscriptionId
$env:AZURE_AI_PROJECT_ENDPOINT = $deployment.properties.outputs.foundryProjectEndpoint.value
$env:AZURE_SEARCH_ENDPOINT = $deployment.properties.outputs.searchEndpoint.value
$env:AZURE_OPENAI_ENDPOINT = $deployment.properties.outputs.openaiEndpoint.value
$env:AZURE_CONTAINER_REGISTRY_ENDPOINT = $deployment.properties.outputs.acrLoginServer.value

Write-Host ""
Write-Host "Set environment variables:" -ForegroundColor Cyan
Write-Host "`$env:AZURE_RESOURCE_GROUP = `"$resourceGroupName`""
Write-Host "`$env:AZURE_SUBSCRIPTION_ID = `"$subscriptionId`""
Write-Host "`$env:AZURE_AI_PROJECT_ENDPOINT = `"$($deployment.properties.outputs.foundryProjectEndpoint.value)`""
Write-Host "`$env:AZURE_SEARCH_ENDPOINT = `"$($deployment.properties.outputs.searchEndpoint.value)`""
Write-Host "`$env:AZURE_OPENAI_ENDPOINT = `"$($deployment.properties.outputs.openaiEndpoint.value)`""

exit 0
