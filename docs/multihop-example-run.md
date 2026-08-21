# Multi-Hop Query Run Example

Verbatim CLI output from a live run against the deployed Azure environment,
demonstrating the multi-hop contrast/compare capability described in
[`architecture.md`](architecture.md) (Flow B).

```powershell
.\scripts\try-orchestrator.ps1 -Query "Contrast the Falcon compressor price with Falcon's cost variance."
```

## Output

```
Using Azure AI Search index: https://agentrouterdevsearch.search.windows.net / agent-cards
Using embedding model: text-embedding-3-small
Using routing model: gpt-5.4-nano

=== Agent Routing Demo (multi-hop) ===
Query: Contrast the Falcon compressor price with Falcon's cost variance.

[Decompose] Query looks compound; asking reasoning model to split it...
[Decompose] Completed in 7751 ms -> 2 sub-queries:
  1. What is the Falcon compressor price?
  2. What is Falcon's cost variance?

[Hop] Routing sub-query: What is the Falcon compressor price?
[Hop] Selected Materials and Procurement Agent (procurement)

[A2A] Loading selected Agent Card from Azure AI Search payload
[A2A] Agent: Materials and Procurement Agent
[A2A] Endpoint: https://agent-router-dev-procure.reddune-9bbf2272.eastus.azurecontainerapps.io/a2a
[A2A] Question: What is the Falcon compressor price?
[A2A] Response: {"agent": "procurement", "project": "Falcon", "answer": "The latest Falcon compressor price is EUR 8.6 million from Siemens Energy."}
[A2A] Completed in 820 ms

[Hop] Routing sub-query: What is Falcon's cost variance?
[Hop] Selected Project Controls Agent (project-controls)

[A2A] Loading selected Agent Card from Azure AI Search payload
[A2A] Agent: Project Controls Agent
[A2A] Endpoint: https://agent-router-dev-controls.reddune-9bbf2272.eastus.azurecontainerapps.io/a2a
[A2A] Question: What is Falcon's cost variance?
[A2A] Response: {"agent": "project-controls", "project": "Falcon", "answer": "The project is EUR 4.4 million above baseline, mainly due to schedule delay and rework."}
[A2A] Completed in 926 ms

[Synthesize] Combining sub-answers into one response...
[Synthesize] Completed in 3487 ms

[Combined answer] The Falcon compressor price is EUR 8.6 million (from Siemens Energy). Falcon's cost variance is EUR 4.4 million above baseline, driven mainly by schedule delay and rework - so the variance is less than the compressor price.

[Performance]
  Overall time: 16626 ms
  AI Search time (all hops): 3640 ms
  Reasoning time (decompose + synthesize): 11238 ms
  A2A time (all hops): 1748 ms
  Uninstrumented overhead: 5 ms

[Reasoning tokens]
  Input tokens: 344
  Output tokens: 88
  Total tokens: 432

[Summary]
{
  "outcome": "multi-hop",
  "sub_queries": [
    "What is the Falcon compressor price?",
    "What is Falcon's cost variance?"
  ],
  "hops": [
    {
      "sub_query": "What is the Falcon compressor price?",
      "agent": "procurement",
      "answer": "{\"agent\": \"procurement\", \"project\": \"Falcon\", \"answer\": \"The latest Falcon compressor price is EUR 8.6 million from Siemens Energy.\"}",
      "clarification": null
    },
    {
      "sub_query": "What is Falcon's cost variance?",
      "agent": "project-controls",
      "answer": "{\"agent\": \"project-controls\", \"project\": \"Falcon\", \"answer\": \"The project is EUR 4.4 million above baseline, mainly due to schedule delay and rework.\"}",
      "clarification": null
    }
  ],
  "combined_answer": "The Falcon compressor price is EUR 8.6 million (from Siemens Energy). Falcon's cost variance is EUR 4.4 million above baseline, driven mainly by schedule delay and rework - so the variance is less than the compressor price."
}
```

## Related docs

- [`docs/architecture.md`](architecture.md) — technical handover, Flow B (multi-hop)
- [`docs/demos.md`](demos.md) — all demo scenarios
- [`docs/perf-journal.md`](perf-journal.md) — performance experiment log
