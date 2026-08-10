# Reproducible demo

Start iGraph in demo mode, compile the request, and save the JSON response as a
local Change Receipt/Pact pair:

```bash
export IGRAPH_CONTEXT_MODE=demo
uvicorn igraph.api:app --port 8000
curl -s http://localhost:8000/v1/analyze \
  -H 'content-type: application/json' \
  --data @examples/change-request.json > /tmp/igraph-analysis.json
```

The response contains:

- `pact`: signed authority, execution scope, artifact hashes, and postconditions;
- `receipt`: review artifacts, validation states, and write-back mode.

The demo fixture intentionally has dashboard and ML dependencies, so staging may
return `require_approval`. To prove a successful simulator call, use the returned
`migration.sql` hash with `human_approved: true` and `target: staging`. To prove
fail-closed behavior, change one Pact field or use `target: production`; the
executor must not be invoked.
