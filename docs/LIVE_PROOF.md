# iGraph live proof

This page records the public GitHub Actions proof for the merged iGraph code.

## Merged code

- Repository: https://github.com/etvjay/iGraph
- Main commit: `c9fc5dd92d024793dc20a037ff9feafeb22a92a5`
- PR #2: https://github.com/etvjay/iGraph/pull/2
- Evidence documentation: https://github.com/etvjay/iGraph/pull/3
- Post-merge CI: https://github.com/etvjay/iGraph/actions/runs/31621253879

## Recorded live results

The corrected live-proof workflow ran against DataHub OSS and produced these results:

- `/health`: `context_mode=live`, `datahub_configured=true`, write-back disabled.
- `/v1/discover`: 10 live candidates; the selected `warehouses` context had 41 downstream
  assets, 3 downstream dashboards, and risk score 55.
- `/v1/analyze`: complete live `warehouses` context, high risk 55/100, context
  fingerprint `1da0ef57ef64e47c`, and signed Pact `igp_cb78546442ad`.
- `/v1/verify`: live post-read verification returned `verified=true` with complete
  retrieval. This was a re-read proof; no real DataHub mutation was attempted.
- Tampered Pact: `deny`, `executor_invoked=false`.
- Expired Pact: `pact_stale`, `executor_invoked=false`.
- Missing live context: `context_unavailable` / HTTP 503, with no fixture fallback.

Download the complete corrected proof artifact from run #9:
https://github.com/etvjay/iGraph/actions/runs/31620540189/artifacts/9151279245

## Claim boundary

This proves live reads, discovery, Pact signing, live post-read verification,
enforcement denial, expiry rejection, and fail-closed behavior. It does not prove
a real database mutation, DataHub write-back, production deployment, or a deployed
public video. Authorized staging execution and one-shot replay protection are
covered by the follow-up proof workflow in the associated pull request.
