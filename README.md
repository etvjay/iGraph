# iGraph

**Context-aware change control for autonomous data agents.**

> Before an agent changes your data infrastructure, it should know what it can break.

`iGraph` uses DataHub context to turn a proposed data change into an explicit blast radius, deterministic risk assessment, machine-readable **Impact Pact**, guarded action decisions, validation requirements, and an auditable **Change Receipt**.

Built for **Build with DataHub: The Agent Hackathon 2026** — target category: **Agents That Do Real Work**.

## Why

Coding agents increasingly know *how* to alter schemas, dbt models, pipelines and configs. They often do not know the organizational consequences of a technically valid change: which dashboards, ML features, owners, domains, assertions or governed assets depend on it.

DataHub already knows those relationships. iGraph turns that context into an execution boundary.

```text
Proposed change
      ↓
DataHub context
      ↓
Lineage / impact graph
      ↓
Deterministic risk classification
      ↓
Impact Pact
      ↓
Guarded agent actions
      ↓
Validation
      ↓
Change Receipt
      ↓
DataHub write-back
```

## Current vertical slice

The repository already implements:

- typed change, context, risk, Pact and receipt models;
- DataHub GraphQL search + downstream-lineage adapter;
- deterministic showcase-shaped fallback mode;
- consequence scoring based on fanout, dashboards, ML dependencies, domains and breaking schema actions;
- explicit allowlist/blocklist Impact Pacts;
- deny-by-default action guard;
- an intentionally blocked `deploy_production` demo path for high-risk changes;
- validation requirements derived from impact context;
- prepared DataHub write-back payloads;
- a FastAPI endpoint;
- a single-screen Change Chamber demo UI;
- tests for high-risk blocking and deny-by-default behavior.

## Golden demo

Propose:

```json
{
  "action": "rename_column",
  "entity": "orders",
  "field": "customer_id",
  "replacement": "account_id"
}
```

iGraph resolves the asset, traverses downstream impact, scores the risk, builds a Pact, allows reviewable artifact generation and blocks an unauthorized production deployment.

The key moment is not that the agent can generate SQL. It is that contextual metadata becomes **machine-enforceable policy**.

## Run locally

### 1. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start the API

```bash
uvicorn igraph.api:app --reload --port 8000
```

### 3. Open the UI

Serve the static directory in another terminal:

```bash
python -m http.server 3000 --directory web
```

Open `http://localhost:3000`.

## DataHub modes

### Demo mode

If `DATAHUB_GMS_URL` is absent, iGraph uses deterministic showcase-shaped metadata so the complete guardrail workflow can be demonstrated without credentials.

### Live DataHub OSS

Run DataHub using the official quickstart, then configure:

```bash
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_TOKEN=""
```

For the hackathon dataset:

```bash
datahub datapack load showcase-ecommerce
```

The adapter uses DataHub GraphQL search to resolve a dataset and downstream lineage to construct the initial impact graph.

## API

### `POST /v1/analyze`

```bash
curl -s http://localhost:8000/v1/analyze \
  -H 'content-type: application/json' \
  -d '{
    "action":"rename_column",
    "entity":"orders",
    "field":"customer_id",
    "replacement":"account_id"
  }'
```

Response structure:

```text
pact
├── request
├── DataHub context
├── risk assessment
├── allowed actions
├── blocked actions
└── required validations

receipt
├── attempted actions
├── denied actions
├── generated artifacts
├── validations
└── write-back payload
```

## Risk model

Risk is deterministic; the LLM is not trusted to grant itself permission.

Current signals include:

- downstream fanout;
- dashboard dependencies;
- ML feature/model dependencies;
- cross-domain impact;
- breaking schema changes;
- sensitive-data classifications.

Risk tiers are `low`, `medium`, `high`, and `critical`.

High/critical Pacts block production deployment and require human approval.

## Impact Pact

An Impact Pact is a temporary machine-readable execution envelope derived from DataHub context. It answers:

- what change was requested;
- what the change affects;
- why it is risky;
- what the agent may do;
- what the agent may not do;
- what must be validated before review/deployment.

## Change Receipt

A Change Receipt records the consequence chain:

```text
Context → Decision → Action → Evidence
```

The receipt makes allowed and denied behavior inspectable instead of hiding the agent's work behind a chat response.

## Next milestones

1. Bind the golden demo to a real high-fanout entity in `showcase-ecommerce`.
2. Pull ownership, domains, tags and assertions from live DataHub, not only lineage.
3. Generate a real migration + regression test from the proposed change.
4. Re-query DataHub after execution to compare pre-change and post-change impact.
5. Emit real DataHub write-back metadata (structured property/tag/document) rather than only preparing the write-back payload.
6. Add a public hosted demo and record the <3 minute submission video.
7. Add sample `impact-pact.json`, `impact-report.md` and `change-receipt.json` generated from the live scenario.

## License

Apache License 2.0.
