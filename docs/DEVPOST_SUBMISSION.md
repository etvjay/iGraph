# Devpost submission draft

## Tagline

Turn DataHub context into the exact authority an autonomous data-change agent may use.

## Short description

iGraph is a context-derived execution guard for autonomous schema and data-asset
changes. It reads DataHub metadata through the SDK and Agent Context Kit, computes a
canonical consequence fingerprint, and compiles a signed, expiring Impact Pact with
action-specific allow/deny/approval decisions. A separate enforcement point checks
the Pact, target, artifact hash, expiry, and one-shot invocation limit before any
executor is reached. A Change Receipt records the decision, executor evidence,
validation states, and optional DataHub custom-property/Document write-back.

## What the recorded proof demonstrates

1. Live DataHub context is available and discovery selects a real showcase asset.
2. The selected `order_items` context contains 37 downstream assets and 3 dashboards,
   producing a high-risk 55/100 signed Pact.
3. An explicitly approved `deploy_staging` action reaches only the reversible
   staging simulator and returns an executed receipt with evidence.
4. Repeating the same signed request is denied before a second executor invocation.
5. A tampered Pact is denied before executor invocation.
6. An expired Pact is rejected as `pact_stale` before executor invocation.
7. Unavailable live context fails closed as `context_unavailable` / HTTP 503;
   iGraph does not substitute fixture metadata.
8. Live post-read verification returns complete live context; it does not claim that
   a real DataHub mutation occurred.

The 10-second video is a silent, deterministic vector reconstruction of the
control-room visual language, populated from recorded proof data. It is labeled as
a reconstruction and does not claim a production deployment, real database
mutation, or DataHub write-back.

## Built with

- DataHub OSS / DataHub SDK
- DataHub Agent Context Kit (`datahub-agent-context`)
- FastAPI, Pydantic, and Python
- DataHub showcase-ecommerce datapack for the live proof

## Links to include

- Public source repository: `https://github.com/etvjay/iGraph`
- Live proof run: `https://github.com/etvjay/iGraph/actions/runs/31740530138`
- Live proof artifact: `https://github.com/etvjay/iGraph/actions/runs/31740530138/artifacts/9197189421`
- Reproducible request: [`examples/change-request.json`](../examples/change-request.json)
- Video asset: `igraph-demo-candidate.mp4` from the accompanying demo package

## Honest scope

The built-in executor is a reversible staging simulator. Production deployment,
real database mutation, and DataHub write-back remain outside this proof. The
live proof keeps `IGRAPH_ENABLE_WRITEBACK=false`.
