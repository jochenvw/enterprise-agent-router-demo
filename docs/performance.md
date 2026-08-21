# Performance results

Setup and reproduction only. Full experiment log with methodology, root-cause analysis,
and per-experiment before/after numbers lives in [`perf-journal.md`](perf-journal.md).
Architecture and demo usage: [`../README.md`](../README.md). Azure deployment: [`infra-deployment.md`](infra-deployment.md).

## Reproduce

Requires infra already deployed (`infra/deploy.ps1`), so `infra/.deployment-outputs.json` exists.

```powershell
# Single query, cold process, full verbose trace
.\scripts\try-orchestrator.ps1 -Query "What is the EAC for Falcon?"

# 10 similar queries in one warm process (default fast path)
.\scripts\demo-queries.ps1

# Same 10 queries, with GPT-5.4-nano reasoning forced on for comparison
.\scripts\demo-queries.ps1 -ForceReasoning

# Router accuracy regression check
$outputs = Get-Content infra\.deployment-outputs.json | ConvertFrom-Json
$env:AZURE_SEARCH_ENDPOINT = $outputs.searchEndpoint.value
$env:AZURE_SEARCH_INDEX_NAME = 'agent-cards'
$env:AZURE_SEARCH_ADMIN_KEY = az search admin-key show --resource-group agent-router-dev-rg --service-name agentrouterdevsearch --query primaryKey -o tsv
$env:AZURE_OPENAI_ENDPOINT = $outputs.openaiEndpoint.value
$env:AZURE_OPENAI_EMBEDDING_DEPLOYMENT = 'text-embedding-3-small'
uv run eval-router
```

## Headline numbers (warm, steady-state)

| Metric | Default fast path | `--force-reasoning` |
|---|---|---|
| Overall time / query | ~1.0 s | ~4.6 s |
| Tokens / query | 0 | ~484 |

See `perf-journal.md` for the full breakdown (AI Search / Reasoning / A2A split, cold-start
analysis, and why the default path is retrieval + rules rather than agentic reasoning).
