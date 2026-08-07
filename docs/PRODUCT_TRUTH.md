# iGraph Product Truth

## Product category

**Context-derived execution control for autonomous data changes.**

## One-line definition

> iGraph converts live data context into bounded agent authority.

## Primary user

Data platform and data engineering teams that are beginning to let autonomous agents modify schemas, transformations, pipelines, or related data infrastructure.

## Painful moment

An agent knows how to make a technically valid change, but the organization lacks a machine-enforceable way to translate the current downstream consequences of that change into the exact authority the agent should receive.

## Canonical primitives

### Impact Pact

The pre-action authority object. It binds a proposed change to:

- the DataHub context snapshot that justified it;
- a context fingerprint;
- deterministic risk;
- allowed actions;
- blocked actions;
- approval requirements;
- required validation.

An Impact Pact is not a natural-language recommendation. It is the execution envelope consumed by the enforcement point.

### Change Receipt

The post-action evidence object. It records:

- Pact ID and context fingerprint;
- attempted actions;
- allow/deny decisions;
- whether an executor was actually invoked;
- generated artifacts and hashes;
- validation evidence;
- resulting write-back state.

## Product invariant

> The agent's capabilities do not determine its authority. The consequences of the action do.

For the same requested change and the same executor, a change in organizational context can legitimately produce a different Impact Pact and therefore different executable authority.

## Decisive workflow

```text
Proposed data change
→ DataHub context
→ context fingerprint
→ consequence analysis
→ Impact Pact
→ enforcement point
   ├─ allowed → executor
   └─ denied  → executor never invoked
→ validation
→ post-change context
→ Change Receipt
→ DataHub write-back
```

## Non-goals

For the hackathon MVP, iGraph is **not**:

- a replacement metadata catalog;
- a generic lineage viewer;
- an AI SQL copilot;
- a generic policy engine;
- a generic coordination-graph platform;
- a production database deployment system;
- a claim that lineage-aware change prevention is novel.

## DataHub relationship

DataHub is the context substrate. iGraph depends on it for organizational state such as schema, lineage, ownership, domains, tags, assertions, and downstream dependencies.

iGraph's product boundary begins when that context is compiled into action-specific authority.

## Evidence boundary

Implemented in-repo:

- Impact Pact model;
- context fingerprinting;
- deterministic risk evaluation;
- deny-by-default guard;
- separate enforcement point;
- executor invocation evidence;
- generated review artifacts;
- Change Receipt model;
- authority-drift experiment fixture.

Requires live proof before strong public claims:

- real showcase-ecommerce DataHub context;
- live context drift detection;
- real DataHub write-back;
- post-change graph verification;
- external staging/data executor integration.
