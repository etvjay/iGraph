# iGraph

**Context-derived execution control for autonomous data changes.**

iGraph turns DataHub context into a signed, bounded authority object (an **Impact
Pact**), checks that object again immediately before a side effect, and emits a
machine-readable **Change Receipt**. The agent may propose a change; it cannot
silently widen the authority granted by the Pact.

Built for **Build with DataHub: The Agent Hackathon 2026** (Agents That Do Real
Work).

## Why this exists

Lineage alone tells us what an asset affects. It does not answer the execution
question: “what may this agent do right now, given those consequences?” iGraph
compiles schema, lineage, ownership, domains, tags, glossary terms, data-quality
assertions, query usage, and retrieval completeness into action-specific authority.

The same request and executor can therefore receive different authority when the
organizational context changes:

```text
proposed change → DataHub / Agent Context Kit → fingerprint → risk
      → signed Impact Pact → enforcement point → executor or no executor
      → verification → Change Receipt → optional DataHub write-back
```

## Security invariants

- Live mode is fail-closed. A timeout, missing entity, incomplete lineage read, or
  missing GMS URL produces `context_unavailable`; it never becomes a demo success.
- Pacts are HMAC-signed (`IGRAPH_SIGNING_SECRET`), expire after 30 minutes, and
  bind the request, context fingerprint, policy version, artifact hashes, target,
  and postconditions.
- The enforcement point validates target and artifact parameters against the signed
  Pact. A denied or stale action has `executor_invoked=false`.
- Decisions are explicit: `allow`, `deny`, `require_approval`,
  `require_migration`, `context_unavailable`, or `pact_stale`.
- Verification checks actual post-change schema conditions. A live read alone is
  not reported as a successful change.

## DataHub integration

The live adapter uses the DataHub SDK plus the official **DataHub Agent Context
Kit** (`datahub-agent-context`). It uses context-first calls for batched entity
enrichment, multi-hop lineage, schema fields, query history, assertions, and
`save_document` write-back. DataHub Skills are the orchestration layer to place
above these tools; iGraph deliberately owns the narrower change-authority boundary
instead of becoming another analytics copilot.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn igraph.api:app --reload --port 8000
```

Serve the UI in another terminal:

```bash
python -m http.server 3000 --directory web
```

### Explicit modes

Demo mode is deterministic and requires no DataHub:

```bash
export IGRAPH_CONTEXT_MODE=demo
unset DATAHUB_GMS_URL
```

Live mode requires a reachable GMS and a secret that is kept outside source
control:

```bash
export IGRAPH_CONTEXT_MODE=live
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_TOKEN=""
export IGRAPH_SIGNING_SECRET="$(openssl rand -hex 32)"
export IGRAPH_ENABLE_WRITEBACK=false
```

For the showcase graph:

```bash
datahub datapack load showcase-ecommerce
curl 'http://localhost:8000/v1/discover'
```

Write-back is opt-in. It preserves existing custom properties, adds `igraph.*`
receipt properties, and saves a linked Agent Context Kit Decision document:

```bash
export IGRAPH_ENABLE_WRITEBACK=true
```

## API walkthrough

Compile a Pact:

```bash
curl -s http://localhost:8000/v1/analyze \
  -H 'content-type: application/json' \
  -d '{"action":"rename_column","entity":"orders","field":"customer_id","replacement":"account_id"}'
```

Execute only with an artifact hash and an in-scope target. Use the `pact` returned
above; do not edit it:

```json
{
  "pact": "<the returned pact>",
  "action": "deploy_staging",
  "parameters": {"target": "staging", "artifact_sha256": "<migration hash>"},
  "human_approved": false
}
```

Other endpoints:

- `POST /v1/verify` — re-read post-change context and evaluate every Pact
  postcondition.
- `GET /v1/discover` — rank live datasets by downstream consequence.
- `GET /v1/experiments/authority-drift` — deterministic A/B proof that context
  changes authority while the request and executor stay constant.
- `GET /health` — reports mode, DataHub configuration, and write-back state.

## Tests and quality gates

```bash
ruff check igraph tests
pytest -q
```

The suite covers canonical fingerprints, live fail-closed behavior, signature
tampering, expiry, parameter scope, approval gating, executor non-invocation,
and postcondition verification.

## Scope

iGraph is not a replacement catalog, a generic lineage viewer, an analytics
copilot, or a production deployment system. The product claim is intentionally
narrow:

> **Current organizational context determines action-specific authority, and the
> enforcement point proves whether a side effect was actually reached.**

See [`docs/PRODUCT_TRUTH.md`](docs/PRODUCT_TRUTH.md) and [`examples/`](examples/)
for the evidence boundary and a reproducible demo request.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
