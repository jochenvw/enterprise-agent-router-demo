# Enterprise agent router demo

This demo makes agent discovery and routing visible. Five deliberately overlapping energy-investment agents expose A2A 1.0 Agent Cards. A registry indexes one document per skill, and an orchestrator retrieves candidates, clarifies ambiguous requests, and delegates to the selected agent over A2A.

## Run locally

```powershell
$env:UV_DEFAULT_INDEX="https://packagefeedproxy.microsoft.io/pypi/simple"
uv sync --python 3.12
uv run serve-agent --agent capital-projects --port 8001
uv run serve-agent --agent project-controls --port 8002
uv run serve-agent --agent procurement --port 8003
uv run serve-agent --agent investment-planning --port 8004
uv run serve-agent --agent consulting --port 8005
```

In another terminal:

```powershell
uv run index-agents
uv run route-query "What is the EAC for Falcon?" --delegate
uv run route-query "What's the status of Falcon?"
uv run eval-router
```

For a demo-friendly trace of the selection mechanism against Azure AI Search:

```powershell
.\scripts\try-orchestrator.ps1 -Query "What is the EAC for Falcon?"
.\scripts\try-orchestrator.ps1 -Query "What's the status of Falcon?"
```

`registry/agents.yaml` is the only list known to the indexer. Add another base URL, rerun `index-agents`, and the orchestrator can retrieve it without a code change.

## Azure mode

Set these variables before indexing and routing:

```text
AZURE_SEARCH_ENDPOINT
AZURE_SEARCH_INDEX_NAME=agent-capabilities
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_EMBEDDING_DEPLOYMENT
AZURE_OPENAI_REASONING_DEPLOYMENT=gpt-5.4-nano
AZURE_OPENAI_API_VERSION=2024-10-21
APPLICATIONINSIGHTS_CONNECTION_STRING
```

Authentication uses `DefaultAzureCredential`; use managed identity in Azure. Without Azure configuration, the demo uses a persisted local capability index with lexical plus deterministic vector scoring.

The specialist agents are intentionally deterministic. The intelligence under test is capability discovery, ambiguity handling, and delegation—not five independent RAG systems.

## Documentation

- [`docs/demos.md`](docs/demos.md) — demo scenarios: single-hop routing, ambiguity/clarification, forced reasoning, multi-hop contrast/compare, batch and eval runs
- [`docs/infra-deployment.md`](docs/infra-deployment.md) — Azure infrastructure deployment, cost estimates, cleanup
- [`docs/performance.md`](docs/performance.md) — performance setup/reproduction and headline numbers
- [`docs/perf-journal.md`](docs/perf-journal.md) — full performance experiment log (methodology, root-cause analysis, before/after measurements)
