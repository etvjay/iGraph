# iGraph live proof

This page records the public GitHub Actions proof for the iGraph control plane.

## Code and checks

- Repository: https://github.com/etvjay/iGraph
- Main branch: https://github.com/etvjay/iGraph/tree/main
- Proof change: https://github.com/etvjay/iGraph/pull/4
- Ordinary CI for the proof branch: https://github.com/etvjay/iGraph/actions/runs/31742150917

## Recorded live results

Live proof run #13 ran against DataHub OSS and produced these results:

- `/health`: `context_mode=live`, `datahub_configured=true`, write-back disabled.
- `/v1/discover`: live discovery selected the `order_items` context. The compiled
  context contained 37 downstream assets, 3 dashboards, and high risk 55/100.
- `/v1/analyze`: signed Pact `igp_a2743e1961fb` with context fingerprint
  `acc76d9fbdaecbfe`, complete live retrieval, and staging scope requiring human approval.
- `/v1/verify`: live post-read verification returned `verified=true` with complete
  retrieval. This was a re-read proof; no real DataHub mutation was attempted.
- Authorized staging action: with explicit approval, the reversible staging simulator
  returned `executed`, `executor_invoked=true`, and a receipt with evidence.
- Same-request replay: returned `denied` with `executor_invoked=false` because the
  Pact invocation limit had already been consumed.
- Tampered Pact: `deny`, `executor_invoked=false`.
- Expired Pact: `pact_stale`, `executor_invoked=false`.
- Missing live context: `context_unavailable` / HTTP 503, with no fixture fallback.

Download the complete proof artifact from run #13:
https://github.com/etvjay/iGraph/actions/runs/31742150914/artifacts/9197797604

## Claim boundary

This proves live reads, discovery, Pact signing, live post-read verification,
authorized reversible staging execution, one-shot replay protection, enforcement
denial, expiry rejection, and fail-closed behavior. It does not prove a real
database mutation, DataHub write-back, production deployment, or a deployed
public video.
