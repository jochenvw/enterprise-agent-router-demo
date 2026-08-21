#!/usr/bin/env pwsh
param(
  [switch]$NoDelegate,
  [switch]$ForceReasoning
)

# Runs all 10 demo queries inside a single Python process (route-query-batch) so the
# ~2s per-process cold start (Azure AD token acquisition + Azure OpenAI client init) is
# paid once for the whole batch instead of once per query. See docs/perf-journal.md, Experiment 4.

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

$queriesFile = Join-Path $PSScriptRoot 'falcon-queries.txt'
$argsList = @('run', 'route-query-batch', $queriesFile, '--verbose')
if (!$NoDelegate) {
  $argsList += '--delegate'
}
if ($ForceReasoning) {
  $argsList += '--force-reasoning'
}

uv @argsList
