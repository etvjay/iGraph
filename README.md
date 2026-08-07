# iGraph

**Context-derived execution control for autonomous data changes.**

> **iGraph converts live data context into bounded agent authority.**

Built for **Build with DataHub: The Agent Hackathon 2026** — target category: **Agents That Do Real Work**.

## The problem

Autonomous coding and data agents increasingly know *how* to alter schemas, transformations, pipelines, and configuration. That does not mean they should automatically receive authority to perform every technically possible action.

The missing question is:

> **Given what this change affects right now, what exactly should this agent be allowed to do?**

DataHub already knows much of the organizational context: schemas, lineage, owners, domains, tags, assertions, dashboards, and downstream dependencies. iGraph compiles that live context into an execution boundary.

```text
Proposed data change
      ↓
DataHub context
      ↓
Context fingerprint
      ↓
Consequence analysis
      ↓
Impact Pact
      ↓
Enforcement point
   ┌──────┴──────┐
 allowed       denied
   │              │
executor       executor never runs
   └──────┬───────┘
          ↓
      validation
          ↓
 post-change context
          ↓
    Change Receipt
          ↓
 DataHub write-back
```

## Canonical primitives

### Impact Pact

The **pre-action authority object**. It binds a proposed change to:

- the DataHub context snapshot that justified it;
- a context fingerprint;
- deterministic risk;
- allowed actions;
- blocked actions;
- human-approval requirements;
- required validations.

The Pact is not an AI recommendation. It is consumed by a separate enforcement point.

### Change Receipt

The **post-action evidence object**. It records:

- the Pact and context fingerprint;
- attempted actions;
- allow/deny decisions;
- whether an executor was actually invoked;
- generated artifacts and SHA-256 hashes;
- validation evidence;
- write-back state.

The core invariant is:

> **The agent's capabilities do not determine its authority. The consequences of the action do.**

## Decisive A/B experiment

The repository exposes a deterministic fixture proving the product claim:

```bash
curl http://localhost:8000/v1/experiments/authority-drift
```

It keeps the **request, agent capability, and executor unchanged** while changing only the organizational context.

Before:

```text
orders.customer_id
→ one ordinary downstream dataset
→ low risk
→ deploy_staging ALLOWED
```

After:

```text
orders.customer_id
→ PII classification
→ executive revenue dashboard
→ production ML dependency
→ multiple domains
→ critical risk
→ deploy_staging BLOCKED
```

The same requested change therefore compiles into different authority.

## Enforcement is not decorative

Guarded actions use a separate enforcement point. A denied action returns evidence that:

```text
executor_invoked = false
```

so a UI cannot claim an action was blocked after an executor already received it.

The hackathon-safe built-in executor is a reversible `deploy_staging` simulator. Production deployment remains outside the MVP.

## Current vertical slice

Implemented:

- typed DataHub context, risk, Pact, execution, receipt, and verification models;
- DataHub SDK search and multi-hop downstream-lineage integration;
- deterministic showcase-shaped fallback mode;
- context fingerprinting;
- deterministic consequence scoring;
- Impact Pact compiler;
- deny-by-default action guard;
- separate execution enforcement point;
- executor invocation evidence;
- generated SQL migration and regression-test artifacts with hashes;
- explicit `pass`, `warning`, `pending`, and `fail` validation states;
- post-change verification endpoint;
- opt-in DataHub metadata write-back;
- golden-demo dataset discovery endpoint;
- authority-drift experiment;
- CI with Ruff + pytest.

See [`docs/PRODUCT_TRUTH.md`](docs/PRODUCT_TRUTH.md) for protected scope and evidence boundaries.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn igraph.api:app --reload --port 8000
```

Serve the static UI separately:

```bash
python -m http.server 3000 --directory web
```

## DataHub modes

### Demo mode

Leave `DATAHUB_GMS_URL` unset. iGraph uses deterministic metadata and marks it as demo context.

### Live DataHub OSS

```bash
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_TOKEN=""
export IGRAPH_ENABLE_WRITEBACK=false
```

Load the hackathon datapack:

```bash
datahub datapack load showcase-ecommerce
```

Then find a high-consequence demo asset:

```bash
curl 'http://localhost:8000/v1/discover'
```

Only after verifying reads should write-back be enabled:

```bash
export IGRAPH_ENABLE_WRITEBACK=true
```

## API

### Analyze and compile an Impact Pact

`POST /v1/analyze`

```json
{
  "action": "rename_column",
  "entity": "orders",
  "field": "customer_id",
  "replacement": "account_id"
}
```

### Enforce an action

`POST /v1/actions/execute`

Send the Pact returned by `/v1/analyze`, an action, and its parameters. iGraph re-checks live context before execution; if the context fingerprint has drifted, the stale Pact fails closed and the executor is not invoked.

### Verify after change

`POST /v1/verify`

Re-reads DataHub and records the post-change context fingerprint.

### Find the golden demo asset

`GET /v1/discover`

Ranks candidate datasets using downstream fanout, dashboards, ML dependencies, and risk score.

### Prove context-derived authority

`GET /v1/experiments/authority-drift`

Returns two Pacts for the same request under different context states and the resulting authority delta.

## Risk model

Risk is deterministic; an LLM is never allowed to grant itself permission.

Signals currently include:

- downstream fanout;
- dashboard dependencies;
- ML dependencies;
- cross-domain impact;
- breaking schema changes;
- sensitive-data classification.

High/critical context removes staging authority and blocks production execution.

## What iGraph is not claiming

The project does **not** claim novelty for:

- lineage analysis;
- blast-radius calculation;
- AI-generated migrations;
- metadata-aware agents;
- generic PR/CI risk blocking.

The product claim is narrower:

> **iGraph converts the current organizational context of a proposed data change into an action-specific, machine-enforced authority object and records the resulting execution evidence.**

## Next proof milestones

1. Run against real `showcase-ecommerce` DataHub metadata.
2. Select the strongest live asset with `/v1/discover`.
3. Demonstrate live Pact recompilation after a real context mutation.
4. Prove stale-Pact rejection against changed live DataHub context.
5. Emit and inspect one real DataHub write-back.
6. Execute one allowed action through a real sandbox adapter.
7. Re-read post-change context and produce the final live Change Receipt.
8. Capture the full A/B flow in the <3-minute demo.

## License

Apache License 2.0.
