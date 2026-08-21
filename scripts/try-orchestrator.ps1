#!/usr/bin/env pwsh
param(
  [string]$Query = "What is the EAC for Falcon?",
  [switch]$NoDelegate,
  [switch]$ForceReasoning
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$outputsPath = Join-Path $repoRoot 'infra\.deployment-outputs.json'
if (!(Test-Path $outputsPath)) {
  throw "Missing $outputsPath. Deploy Azure infrastructure first with .\infra\deploy.ps1."
}

$outputs = Get-Content $outputsPath | ConvertFrom-Json
$env:AZURE_SEARCH_ENDPOINT = $outputs.searchEndpoint.value
$env:AZURE_SEARCH_INDEX_NAME = 'agent-cards'
$env:AZURE_SEARCH_ADMIN_KEY = az search admin-key show `
  --resource-group agent-router-dev-rg `
  --service-name agentrouterdevsearch `
  --query primaryKey -o tsv
if ($LASTEXITCODE -ne 0) {
  throw 'Unable to read Azure AI Search admin key.'
}

$env:AZURE_OPENAI_ENDPOINT = $outputs.openaiEndpoint.value
$env:AZURE_OPENAI_EMBEDDING_DEPLOYMENT = 'text-embedding-3-small'
$env:AZURE_OPENAI_REASONING_DEPLOYMENT = 'gpt-5.4-nano'
$env:AZURE_OPENAI_API_VERSION = '2024-10-21'
$env:APPLICATIONINSIGHTS_CONNECTION_STRING = $outputs.appInsightsConnectionString.value

Write-Host "Using Azure AI Search index: $env:AZURE_SEARCH_ENDPOINT / $env:AZURE_SEARCH_INDEX_NAME" -ForegroundColor Cyan
Write-Host "Using embedding model: $env:AZURE_OPENAI_EMBEDDING_DEPLOYMENT" -ForegroundColor Cyan
Write-Host "Using routing model: $env:AZURE_OPENAI_REASONING_DEPLOYMENT" -ForegroundColor Cyan
Write-Host ""

$argsList = @('run', 'route-query', $Query, '--verbose')
if (!$NoDelegate) {
  $argsList += '--delegate'
}
if ($ForceReasoning) {
  $argsList += '--force-reasoning'
}

uv @argsList
