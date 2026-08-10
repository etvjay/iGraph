from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from igraph.models import (
    ExecutionEvent,
    ExecutionStatus,
    GuardDecision,
    GuardDecisionType,
    ImpactPact,
)

ExecutorFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class EnforcementPoint:
    """The last boundary before an external side effect.

    It validates action parameters against the Pact's immutable execution scope;
    a planner cannot widen a Pact by supplying a different target or artifact.
    """

    executors: dict[str, ExecutorFn]
    consumed_invocations: set[tuple[str, str]] = field(default_factory=set)

    @staticmethod
    def _evidence_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _scope_decision(
        pact: ImpactPact, action: str, parameters: dict[str, Any]
    ) -> GuardDecision | None:
        scope = pact.execution_scope.get(action)
        if scope is None:
            return None

        targets = scope.get("targets") or []
        target = parameters.get("target")
        if targets and target not in targets:
            return GuardDecision(
                action=action,
                allowed=False,
                decision=GuardDecisionType.DENY,
                reason=f"Target {target!r} is outside the Pact execution scope {targets}",
                policy_version=pact.policy_version,
                context_hash=pact.context_hash,
            )

        artifact_hashes = scope.get("artifact_hashes") or []
        artifact_hash = parameters.get("artifact_sha256")
        if artifact_hashes and artifact_hash not in artifact_hashes:
            return GuardDecision(
                action=action,
                allowed=False,
                decision=GuardDecisionType.DENY,
                reason="Artifact hash is missing or is not one of the Pact's review artifacts",
                policy_version=pact.policy_version,
                context_hash=pact.context_hash,
            )
        return None

    def execute(
        self,
        *,
        pact: ImpactPact,
        action: str,
        decision: GuardDecision,
        parameters: dict[str, Any],
        human_approved: bool = False,
    ) -> ExecutionEvent:
        if decision.decision == GuardDecisionType.REQUIRE_APPROVAL:
            if not human_approved:
                approval_decision = decision.model_copy(
                    update={
                        "allowed": False,
                        "reason": "Impact Pact requires explicit human approval for this action",
                    }
                )
                return ExecutionEvent(
                    action=action,
                    status=ExecutionStatus.DENIED,
                    executor_invoked=False,
                    decision=approval_decision,
                    detail="Required approval was absent; executor was not invoked.",
                )
            decision = decision.model_copy(
                update={
                    "allowed": True,
                    "decision": GuardDecisionType.ALLOW,
                    "reason": "Human approval satisfied the Impact Pact requirement",
                }
            )

        if not decision.allowed or decision.decision != GuardDecisionType.ALLOW:
            status = (
                ExecutionStatus.CONTEXT_UNAVAILABLE
                if decision.decision == GuardDecisionType.CONTEXT_UNAVAILABLE
                else ExecutionStatus.PACT_STALE
                if decision.decision == GuardDecisionType.PACT_STALE
                else ExecutionStatus.DENIED
            )
            return ExecutionEvent(
                action=action,
                status=status,
                executor_invoked=False,
                decision=decision,
                detail="Denied before executor invocation by the Impact Pact enforcement point.",
            )

        scope_decision = self._scope_decision(pact, action, parameters)
        if scope_decision is not None:
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.DENIED,
                executor_invoked=False,
                decision=scope_decision,
                detail="Parameters were outside the signed Pact execution scope.",
            )

        scope = pact.execution_scope.get(action) or {}
        max_invocations = int(scope.get("max_invocations", 1))
        invocation_key = (pact.pact_id, action)
        if max_invocations <= 0 or invocation_key in self.consumed_invocations:
            replay_decision = decision.model_copy(
                update={
                    "allowed": False,
                    "decision": GuardDecisionType.DENY,
                    "reason": "Impact Pact invocation limit has already been consumed",
                }
            )
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.DENIED,
                executor_invoked=False,
                decision=replay_decision,
                detail="Replay/duplicate execution was blocked before executor invocation.",
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
            self.consumed_invocations.add(invocation_key)
            result = executor(parameters)
            return ExecutionEvent(
                action=action,
                status=ExecutionStatus.EXECUTED,
                executor_invoked=True,
                decision=decision,
                evidence_sha256=self._evidence_hash(result),
                detail=json.dumps(result, sort_keys=True, default=str),
            )
        except Exception as exc:  # noqa: BLE001 - executor adapters are provider-specific
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
