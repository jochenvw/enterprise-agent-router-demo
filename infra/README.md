# Azure Infrastructure Deployment

Complete IaC for agent router demo: Foundry, AI Search, OpenAI, monitoring, container registry.

## Prerequisites

- Azure CLI (`az`) — [install](https://learn.microsoft.com/cli/azure/install-azure-cli)
- Azure Bicep CLI (`bicep`) — `az bicep install`
- PowerShell 7+ — [install](https://learn.microsoft.com/powershell/scripting/install/installing-powershell)
- Active Azure subscription

## Quick Start

```powershell
# Deploy infrastructure
cd infra
./deploy.ps1 -location eastus -environment dev

# Set environment variables from .deployment-outputs.json
$outputs = Get-Content .deployment-outputs.json | ConvertFrom-Json
$env:AZURE_SEARCH_ENDPOINT = $outputs.searchEndpoint.value
$env:AZURE_OPENAI_ENDPOINT = $outputs.openaiEndpoint.value
$env:AZURE_AI_PROJECT_ENDPOINT = $outputs.foundryProjectEndpoint.value

# Run demo against Azure
cd ..
uv run index-agents
uv run eval-router
uv run route-query "What is the EAC for Falcon?" --delegate
```

## Deployment

Provisions:
- **Azure AI Foundry** Hub + Project (orchestration, model hosting)
- **Azure OpenAI / Foundry** (text-embedding-3-small + gpt-5.4-nano deployments)
- **Azure AI Search** (agent capability index)
- **Application Insights** + Log Analytics (tracing)
- **Container Registry** (agent image hosting)

All deployed to a single resource group in the specified region.

```powershell
./deploy.ps1 `
  -subscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
  -location eastus `
  -environment dev `
  -projectName agent-router
```

Outputs:
- Resource group name
- Foundry project endpoint
- AI Search endpoint
- OpenAI endpoint
- Container registry URL
- Application Insights connection string

Stored to `.deployment-outputs.json` for cleanup reference.

## Cleanup

Delete all resources (irreversible):

```powershell
./cleanup.ps1
```

Auto-detects resource group from `.deployment-outputs.json`. Confirm when prompted.

Or skip confirmation:

```powershell
./cleanup.ps1 -force
```

Deletion runs in the background. Monitor with:

```powershell
az group show --name agent-router-dev-rg
az group wait --name agent-router-dev-rg --deleted
```

## Cost Estimates

Running for 730 hours (1 month):
- **Foundry Hub/Project**: ~USD 10
- **Azure OpenAI** (embeddings + gpt-4o): ~USD 200–500 (depends on query volume)
- **AI Search** (Standard): ~USD 200
- **Application Insights**: ~USD 5
- **Container Registry** (Standard): ~USD 10

**Total**: ~USD 425–715/month.

Reduce by:
- Using Basic AI Search (not recommended for production)
- Scaling down OpenAI deployment capacity
- Deleting after demo
