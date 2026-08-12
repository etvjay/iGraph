# iGraph live proof

This page records the public GitHub Actions proof for the merged iGraph code.

## Merged code

- Repository: https://github.com/etvjay/iGraph
- Main commit: `0136cef2fa556d79f7565999f77cfc92c0a66d42`
- Pull request: https://github.com/etvjay/iGraph/pull/2
- Post-merge CI: https://github.com/etvjay/iGraph/actions/runs/31618368233

## Recorded live results

The live-proof workflow ran against DataHub OSS and produced these results:

- `/health`: `context_mode=live`, `datahub_configured=true`, write-back disabled.
- `/v1/discover`: 10 live candidates; the top candidate is `addresses` with
  22 downstream assets and risk score 55.
- `/v1/analyze`: live `addresses` context with 28 downstream assets, complete
  retrieval, high risk 55/100, and signed Pact `igp_ce855182f9dc`.
- Tampered Pact: `deny`, `executor_invoked=false`.
- Expired Pact: `pact_stale`, `executor_invoked=false`.
- Missing live context: `context_unavailable` / HTTP 503, with no fixture fallback.

Download the complete workflow artifact from the successful proof run:
https://github.com/etvjay/iGraph/actions/runs/31479477960/artifacts/9096775884

## Claim boundary

This proves live reads, discovery, Pact signing, enforcement denial, expiry
rejection, and fail-closed behavior. It does not prove production deployment,
real database mutation, DataHub write-back, or a deployed public video.