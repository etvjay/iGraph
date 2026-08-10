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

## What to show in the video

1. Run the deterministic authority-drift endpoint: the same rename request is
   allowed to stage in an isolated context and blocked in a PII/dashboard/ML
   context.
2. Analyze `orders.customer_id` and show the signed Pact, SQL migration hash, and
   `require_approval` decision.
3. Attempt a tampered Pact or `target=production`; show `executor_invoked=false`.
4. Approve an in-scope staging artifact once; show the simulator receipt and the
   second-attempt replay denial.
5. In live mode, show that a GMS timeout returns `context_unavailable` rather than
   silently using fixture metadata.

## Built with

- DataHub OSS / DataHub SDK
- DataHub Agent Context Kit (`datahub-agent-context`)
- FastAPI, Pydantic, and Python
- DataHub showcase-ecommerce datapack for the live demo

## Links to include

- Public source repository: `https://github.com/Jaydearcadian/iGraph`
- Demo endpoint: `GET /v1/experiments/authority-drift`
- Reproducible request: [`examples/change-request.json`](../examples/change-request.json)

## Honest scope

The built-in executor is a reversible staging simulator. Production deployment,
real database mutation, public repository visibility, and the final hosted video
remain submission/deployment steps outside this code-only patch.
