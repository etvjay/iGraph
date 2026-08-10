"""Small, dependency-free signing helpers for immutable Impact Pacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from igraph.models import ImpactPact


class PactSignatureError(ValueError):
    """Raised when a Pact cannot be trusted."""


class PactSigner:
    """HMAC signer used to prevent callers from widening a returned Pact."""

    def __init__(self, secret: str | None = None) -> None:
        configured = secret if secret is not None else os.getenv("IGRAPH_SIGNING_SECRET")
        # A deterministic dev secret keeps the demo self-contained. Live mode is
        # expected to set a real secret (validated by DataHubAdapter).
        self.secret = (configured or "igraph-demo-signing-secret").encode()

    @staticmethod
    def _payload(pact: ImpactPact) -> dict[str, Any]:
        payload = pact.model_dump(mode="json", exclude={"signature"})
        return payload

    def canonical(self, pact: ImpactPact) -> bytes:
        return json.dumps(
            self._payload(pact), sort_keys=True, separators=(",", ":")
        ).encode()

    def sign(self, pact: ImpactPact) -> str:
        return hmac.new(self.secret, self.canonical(pact), hashlib.sha256).hexdigest()

    def issue(self, pact: ImpactPact) -> ImpactPact:
        return pact.model_copy(update={"signature": self.sign(pact)})

    def verify(self, pact: ImpactPact) -> None:
        expected = self.sign(pact)
        if not pact.signature or not hmac.compare_digest(expected, pact.signature):
            raise PactSignatureError("Impact Pact signature is invalid or has been tampered with")

