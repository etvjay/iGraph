# iGraph Product Truth

## Product category

**Context-derived execution control for autonomous data changes.**

## Primary user and painful moment

Data platform and data engineering teams are beginning to let autonomous agents
modify schemas, transformations, pipelines, or related infrastructure. An agent
may know how to make a technically valid change, while the organization still
lacks a machine-enforceable way to translate current downstream consequences into
the exact authority that agent should receive.

## Canonical primitives

### Impact Pact

The pre-action authority object. A Pact binds:

- the DataHub / Agent Context Kit snapshot that justified the decision;
- a canonical context fingerprint and retrieval-completeness flag;
- deterministic risk and an explicit decision policy;
- allow, deny, and human-approval actions;
- artifact hashes and parameter/target scope;
- expiry, policy version, HMAC signature, and postconditions.

The Pact is not a natural-language recommendation. It is consumed by a separate
enforcement point.

### Change Receipt

The evidence object. A Receipt records the Pact ID and fingerprint, decisions,
whether an executor was invoked, artifact hashes, validation evidence, verification
status, and optional DataHub custom-property/document write-back.

## Product invariant

> The agent's capabilities do not determine its authority. The consequences of the
> action do.

For the same requested change and the same executor, a context change can produce a
different Pact and therefore different executable authority.

## Trust boundary

```text
planner / agent
    │ proposes request and receives Pact
    ▼
DataHub + Agent Context Kit ──► signed Impact Pact
                                  │
                                  ▼
                           enforcement point
                             ├─ allowed + in scope → executor
                             └─ denied / stale / unavailable → no executor
                                  │
                                  ▼
                             Change Receipt
```

Live mode never falls back to fixture metadata. Demo mode is selected explicitly
and every context is marked `live=false`.

## DataHub relationship

DataHub is the context substrate: schema, lineage, ownership, domains, tags,
glossary terms, assertions, query history, documents, and structured properties.
The Agent Context Kit gives iGraph context-first tools and a documented write-back
surface. iGraph's product boundary begins when this context is compiled into
action-specific authority.

## Non-goals

For the hackathon MVP, iGraph is not:

- a replacement metadata catalog;
- a generic lineage viewer;
- an analytics copilot;
- a generic policy engine;
- a production database deployment system;
- a claim that lineage-aware change prevention is novel.

## Evidence boundary

Implemented in-repo:

- typed context, risk, Pact, enforcement, execution, receipt, and verification models;
- DataHub SDK + Agent Context Kit enrichment and optional document write-back;
- explicit demo/live modes with fail-closed live reads;
- canonical context fingerprints;
- deterministic consequence scoring;
- HMAC-signed, expiring Pacts with target/artifact scope;
- explicit decisions and executor invocation evidence;
- generated review artifacts with SHA-256 hashes;
- postcondition-based verification;
- authority-drift experiment fixture;
- tests for tampering, expiry, scope, approval, drift, and unavailable context.

Requires live proof before strong public claims:

- a real `showcase-ecommerce` DataHub context;
- a real DataHub mutation followed by stale-Pact rejection;
- one real custom-property and Agent Context Kit document write-back;
- one sandbox adapter execution and a post-change schema re-read;
- the final <3-minute public demo video.
