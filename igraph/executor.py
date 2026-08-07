from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from igraph.models import ExecutionEvent, ExecutionStatus, GuardDecision, ImpactPact


ExecutorFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class EnforcementPoint:
    """Executes only actions explicitly authorized by an Impact Pact.

    The enforcement point is intentionally separate from the agent/planner.
    A denied action never reaches its executor adapter.
    """

    executors: dict[str, ExecutorFn]

    @staticmethod
    def _evidence_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def execute(
        self,
        *,
        pact: ImpactPact,
        action: str,
        decision: GuardDecision,
        parameters: dict[str, Any],
        human_approved: bool = False,
    ) -> ExecutionEvent:
        if not decision.allowed:
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.DENIED,
                executor_invoked=False,
                decision=decision,
                detail="Denied before executor invocation by the Impact Pact enforcement point.",
            )

        if action in pact.requires_human_approval and not human_approved:
            approval_decision = GuardDecision(
                action=action,
                allowed=False,
                reason="Impact Pact requires explicit human approval for this action",
            )
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.DENIED,
                executor_invoked=False,
                decision=approval_decision,
                detail="Required approval was absent; executor was not invoked.",
            )

        executor = self.executors.get(action)
        if executor is None:
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.PREPARED,
                executor_invoked=False,
                decision=decision,
                detail="Action is authorized, but no executor adapter is registered; prepared for external execution.",
            )

        try:
            result = executor(parameters)
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.EXECUTED,
                executor_invoked=True,
                decision=decision,
                evidence_sha256=self._evidence_hash(result),
                detail=json.dumps(result, sort_keys=True, default=str),
            )
        except Exception as exc:  # pragma: no cover - adapter-specific failure surface
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.FAILED,
                executor_invoked=True,
                decision=decision,
                detail=f"Executor failed: {exc}",
            )


def default_enforcement_point() -> EnforcementPoint:
    def deploy_staging(parameters: dict[str, Any]) -> dict[str, Any]:
        # Hackathon-safe reversible executor. It proves that an authorized action
        # reaches an adapter without pretending to mutate production infrastructure.
        return {
            "adapter": "staging-simulator",
            "status": "accepted",
            "target": parameters.get("target", "staging"),
            "artifact_sha256": parameters.get("artifact_sha256"),
        }

    return EnforcementPoint(executors={"deploy_staging": deploy_staging})
