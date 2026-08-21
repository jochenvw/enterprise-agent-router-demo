#!/usr/bin/env pwsh
param(
  [string]$resourceGroupName = 'agent-router-dev-rg',
  [string]$location = 'eastus',
  [string]$environment = 'dev',
  [string]$projectName = 'agent-router'
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:AZURE_CORE_NO_COLOR = 'true'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-AzCli {
  param([Parameter(Mandatory = $true)][scriptblock]$Command)
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI command failed with exit code $LASTEXITCODE"
  }
}

$acrName = ($projectName + $environment + 'acr') -replace '-', ''
$imageTag = "agent-router:$(Get-Date -Format 'yyyyMMddHHmmss')"
$environmentName = "$projectName-$environment-aca"
$lawName = "$projectName-$environment-law"

Invoke-AzCli { az extension add --name containerapp --upgrade --allow-preview true }
Invoke-AzCli { az provider register --namespace Microsoft.App }
Invoke-AzCli { az provider register --namespace Microsoft.OperationalInsights }

Write-Host "Building image in ACR: $acrName/$imageTag"
Invoke-AzCli { az acr build --registry $acrName --image $imageTag --no-logs . }

$workspaceId = az monitor log-analytics workspace show `
  --resource-group $resourceGroupName `
  --workspace-name $lawName `
  --query customerId -o tsv
if ($LASTEXITCODE -ne 0) { throw "Unable to read Log Analytics workspace id." }

$workspaceKey = az monitor log-analytics workspace get-shared-keys `
  --resource-group $resourceGroupName `
  --workspace-name $lawName `
  --query primarySharedKey -o tsv
if ($LASTEXITCODE -ne 0) { throw "Unable to read Log Analytics workspace key." }

$envExists = az containerapp env show `
  --resource-group $resourceGroupName `
  --name $environmentName `
  --query name -o tsv 2>$null
if (!$envExists) {
  Invoke-AzCli {
    az containerapp env create `
      --resource-group $resourceGroupName `
      --name $environmentName `
      --location $location `
      --logs-workspace-id $workspaceId `
      --logs-workspace-key $workspaceKey
  }
}

$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
$acrUser = az acr credential show --name $acrName --query username -o tsv
$acrPassword = az acr credential show --name $acrName --query passwords[0].value -o tsv
if ($LASTEXITCODE -ne 0) { throw "Unable to read ACR credentials." }

$agents = @(
  @{ Id = 'capital-projects'; Name = 'capproj' },
  @{ Id = 'project-controls'; Name = 'controls' },
  @{ Id = 'procurement'; Name = 'procure' },
  @{ Id = 'investment-planning'; Name = 'invest' },
  @{ Id = 'consulting'; Name = 'consult' }
)

$urls = @()
foreach ($agent in $agents) {
  $appName = "$projectName-$environment-$($agent.Name)"
  $image = "$acrLoginServer/$imageTag"
  $exists = az containerapp show --resource-group $resourceGroupName --name $appName --query name -o tsv 2>$null
  if ($exists) {
    Invoke-AzCli {
      az containerapp update `
        --resource-group $resourceGroupName `
        --name $appName `
        --image $image `
        --set-env-vars AGENT_ID=$($agent.Id) PORT=8000
    }
  } else {
    Invoke-AzCli {
      az containerapp create `
        --resource-group $resourceGroupName `
        --name $appName `
        --environment $environmentName `
        --image $image `
        --target-port 8000 `
        --ingress external `
        --registry-server $acrLoginServer `
        --registry-username $acrUser `
        --registry-password $acrPassword `
        --env-vars AGENT_ID=$($agent.Id) PORT=8000 `
        --min-replicas 1 `
        --max-replicas 1
    }
  }

  $fqdn = az containerapp show --resource-group $resourceGroupName --name $appName --query properties.configuration.ingress.fqdn -o tsv
  if ($LASTEXITCODE -ne 0) { throw "Unable to read FQDN for $appName." }
  $baseUrl = "https://$fqdn"
  Invoke-AzCli {
    az containerapp update `
      --resource-group $resourceGroupName `
      --name $appName `
      --set-env-vars AGENT_ID=$($agent.Id) PORT=8000 PUBLIC_BASE_URL=$baseUrl
  }
  $urls += "  - $baseUrl"
  Write-Host "$($agent.Id): $baseUrl"
}

$configPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'registry\agents.azure.yaml'
"agents:`n$($urls -join "`n")" | Set-Content $configPath
Write-Host "Wrote $configPath"
