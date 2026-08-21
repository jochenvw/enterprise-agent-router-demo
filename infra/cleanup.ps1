#!/usr/bin/env pwsh
<#
.SYNOPSIS
Cleanup agent router demo infrastructure.

.DESCRIPTION
Deletes the resource group and all contained resources.

.PARAMETER resourceGroupName
Resource group name to delete.

.PARAMETER subscriptionId
Azure subscription ID. Defaults to current context.

.PARAMETER force
Skip confirmation prompt.

.EXAMPLE
./cleanup.ps1 -resourceGroupName "agent-router-dev-rg" -force
#>

param(
  [string]$resourceGroupName,
  [string]$subscriptionId,
  [switch]$force
)

$ErrorActionPreference = 'Stop'

# Validate az CLI
if (!(Get-Command az -ErrorAction SilentlyContinue)) {
  Write-Error "Azure CLI not found. Install it and try again."
  exit 1
}

# Set subscription
if ($subscriptionId) {
  Write-Host "Setting subscription: $subscriptionId"
  az account set --subscription $subscriptionId
}

# Auto-detect resource group from deployment outputs
if (!$resourceGroupName) {
  $outputFile = Join-Path $PSScriptRoot '.deployment-outputs.json'
  if (Test-Path $outputFile) {
    $outputs = Get-Content $outputFile | ConvertFrom-Json
    $resourceGroupName = $outputs.resourceGroupName.value
    Write-Host "Detected resource group from deployment outputs: $resourceGroupName"
  } else {
    Write-Error "Resource group name not specified and no deployment outputs found."
    Write-Host "Usage: ./cleanup.ps1 -resourceGroupName 'agent-router-dev-rg'"
    exit 1
  }
}

# Verify resource group exists
$rgExists = az group exists --name $resourceGroupName --output tsv
if ($rgExists -ne 'true') {
  Write-Error "Resource group not found: $resourceGroupName"
  exit 1
}

# Confirm deletion
if (!$force) {
  Write-Host "About to delete resource group: $resourceGroupName" -ForegroundColor Yellow
  Write-Host "This action is IRREVERSIBLE." -ForegroundColor Red
  $response = Read-Host "Type 'yes' to confirm"
  if ($response -ne 'yes') {
    Write-Host "Cleanup cancelled."
    exit 0
  }
}

Write-Host "Deleting resource group: $resourceGroupName..."
az group delete --name $resourceGroupName --yes --no-wait

Write-Host "Resource group deletion initiated (running in background)." -ForegroundColor Green
Write-Host "Monitor progress with:"
Write-Host "  az group show --name $resourceGroupName"
Write-Host ""
Write-Host "Or wait for completion with:"
Write-Host "  az group wait --name $resourceGroupName --deleted"

exit 0
