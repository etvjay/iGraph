# iGraph Change Guard

Use this skill when an agent proposes a schema or data-asset change that could
create downstream consequences.

## Required sequence

1. Call `POST /v1/analyze` with the exact `ChangeRequest`.
2. Treat the returned `pact` as immutable. Preserve its signature, expiry,
   `context_hash`, `execution_scope`, and artifact hashes.
3. Inspect the receipt's generated artifacts and validation states. Do not execute
   when a validation is `fail` or context is unavailable.
4. If executing, pass only an in-scope `target` and a hash of a Pact artifact to
   `POST /v1/actions/execute`. Supply human approval only when the Pact decision is
   `require_approval` and a human actually approved it.
5. Call `POST /v1/verify` after the external change. Report every postcondition;
   `verified=true` requires all of them to pass.

## DataHub context rules

- Use live mode for claims about current organizational state. Never reinterpret a
  demo context (`live=false`) as live evidence.
- A live timeout, missing asset, truncated lineage, or incomplete enrichment is a
  blocker, not an empty graph.
- DataHub Agent Context Kit tools are the context-first enrichment surface; DataHub
  Skills can orchestrate broader search/lineage/quality workflows around this
  guard, but must not bypass the signed enforcement point.

## Decision vocabulary

`allow`, `deny`, `require_approval`, `require_migration`, `context_unavailable`,
and `pact_stale` are distinct states. A denied, stale, or unavailable decision
must have `executor_invoked=false`.
