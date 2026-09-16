# commerce-reasoning

Retail operational ontology, deterministic restock plans, procedural guidance, and a shared host/model execution boundary. Install from this repository with `pip install -r requirements.txt`.

| Module | Responsibility |
|---|---|
| `config.py`, `models.py` | Independent settings and typed domain contracts |
| `ontology.py` | Object classification, relationships, observations, pending snapshots and exact cover-days arithmetic |
| `execution.py` | Trusted task context, host approvals, plan binding, per-round guidance and audit integration |
| `procedural.py`, `guidance.py` | Validated graphs, registered three-valued predicates, directed retrieval and tool-free guidance |
| `storage.py` | Tenant/environment-scoped SQLite sidecars and append-only events |
| `evaluation.py` | Isolated environments, fixed clocks, fault injection, state oracles, token and latency reports |
| `evolution.py` | Restricted candidate patches, validation gates, rejection history and immutable releases |
| `cli.py` | Knowledge validation, evaluation, read-only replay, refinement and release commands |

The retail integration supplies `ReasoningRetailMerchant`, which commits the simulated inventory, shared storefront catalog, change ledger and effect receipt together within one event-loop critical section. Other deployments retain their existing executor by default. Domain models and graph operations have no model-provider imports.

Run `python -m pytest commerce-reasoning/tests`. See [configuration and operation](../docs/ontology-pg/README.md) and [the original specification](../commerce-agents_Ontology_PG_技术设计与实施文档.md).
