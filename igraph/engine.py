from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from igraph.datahub_adapter import ContextUnavailableError, DataHubAdapter
from igraph.executor import EnforcementPoint, default_enforcement_point
from igraph.models import (
    AnalysisResponse,
    AuthorityDelta,
    AuthorityDriftExperiment,
    ChangeReceipt,
    ChangeRequest,
    DataHubContext,
    DiscoveryCandidate,
    DiscoveryResponse,
    ExecuteActionResponse,
    ExecutionEvent,
    ExecutionStatus,
    GeneratedArtifact,
    GuardDecision,
    GuardDecisionType,
    ImpactNode,
    ImpactPact,
    Postcondition,
    RiskAssessment,
    RiskTier,
    ValidationResult,
    ValidationStatus,
    VerificationResponse,
)
from igraph.security import PactSignatureError, PactSigner


@dataclass(slots=True)
class ImpactEngine:
    datahub: DataHubAdapter
    enforcement: EnforcementPoint = field(default_factory=default_enforcement_point)
    signer: PactSigner = field(default_factory=PactSigner)
    pact_ttl_minutes: int = 30

    @staticmethod
    def context_hash(context: DataHubContext) -> str:
        """Hash authoritative metadata canonically, independent of API ordering."""
        payload = context.model_dump(mode="json", exclude={"live"})
        for key in (
            "schema_fields",
            "owners",
            "domains",
            "tags",
            "glossary_terms",
            "assertions",
            "query_usage",
            "documents",
            "retrieval_warnings",
        ):
            payload[key] = sorted(payload.get(key) or [])
        payload["downstream"] = sorted(
            [
                {
                    **node,
                    "tags": sorted(node.get("tags") or []),
                    "column_paths": sorted(node.get("column_paths") or []),
                    "glossary_terms": sorted(node.get("glossary_terms") or []),
                    "quality_statuses": sorted(node.get("quality_statuses") or []),
                }
                for node in payload.get("downstream") or []
            ],
            key=lambda node: (node.get("urn", ""), node.get("depth", 0), node.get("type", "")),
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:16]

    def assess_risk(self, request: ChangeRequest, context: DataHubContext) -> RiskAssessment:
        score = 0
        reasons: list[str] = []
        fanout = len(context.downstream)
        if fanout >= 15:
            score += 35
            reasons.append("high_downstream_fanout")
        elif fanout >= 5:
            score += 22
            reasons.append("moderate_downstream_fanout")
        elif fanout:
            score += 10
            reasons.append("downstream_dependencies_present")

        types = {node.type.lower() for node in context.downstream}
        if "dashboard" in types:
            score += 20
            reasons.append("production_dashboard_dependency")
        if {"ml_feature", "ml_model", "mlfeature", "mlmodel"} & types:
            score += 25
            reasons.append("ml_dependency_detected")
        if len(context.domains) > 1 or len({node.domain for node in context.downstream if node.domain}) > 1:
            score += 12
            reasons.append("cross_domain_change")
        if request.action in {"drop_column", "change_type"}:
            score += 25
            reasons.append("breaking_schema_change")
        classifications = {tag.lower() for tag in context.tags + context.glossary_terms}
        if classifications & {"pii", "sensitive", "restricted"}:
            score += 30
            reasons.append("sensitive_data_classification")
        if context.assertion_statuses and any(
            status.lower() in {"failing", "error"} for status in context.assertion_statuses.values()
        ):
            score += 20
            reasons.append("failing_data_quality_assertion")
        if context.truncated or not context.retrieval_complete:
            score += 25
            reasons.append("incomplete_context_retrieval")

        score = min(score, 100)
        tier = (
            RiskTier.CRITICAL
            if score >= 75
            else RiskTier.HIGH
            if score >= 45
            else RiskTier.MEDIUM
            if score >= 20
            else RiskTier.LOW
        )
        return RiskAssessment(tier=tier, score=score, reasons=reasons or ["isolated_change"])

    def make_pact(self, request: ChangeRequest, context: DataHubContext, risk: RiskAssessment) -> ImpactPact:
        context_hash = self.context_hash(context)
        digest = hashlib.sha256(
            f"{context.source_urn}:{context_hash}:{request.model_dump_json()}".encode()
        ).hexdigest()[:12]
        allowed = ["inspect_context", "generate_migration", "generate_tests", "create_patch"]
        blocked = ["delete_dataset", "alter_unrelated_schema", "deploy_production"]
        approvals: list[str] = []

        # Context changes authority, but the result is explicit: ordinary risk can
        # stage, high risk needs a human, and critical/incomplete context cannot stage.
        if risk.tier in {RiskTier.LOW, RiskTier.MEDIUM} and context.retrieval_complete:
            allowed.append("deploy_staging")
        elif risk.tier == RiskTier.HIGH and context.retrieval_complete:
            allowed.append("deploy_staging")
            approvals.append("deploy_staging")
        else:
            blocked.append("deploy_staging")

        validations = ["schema_compatibility", "lineage_recheck"]
        if any(node.type.lower() == "dashboard" for node in context.downstream):
            validations.append("dashboard_dependency_check")
        if any(node.type.lower() in {"ml_feature", "ml_model", "mlfeature", "mlmodel"} for node in context.downstream):
            validations.append("ml_dependency_check")
        if context.truncated or not context.retrieval_complete:
            validations.append("context_completeness_check")

        postconditions = [Postcondition(name="context_is_live", kind="context_live")]
        if request.action == "rename_column" and request.field and request.replacement:
            postconditions += [
                Postcondition(name="old_field_removed", kind="field_absent", target=request.field),
                Postcondition(name="replacement_field_present", kind="field_present", target=request.replacement),
                Postcondition(name="context_fingerprint_changed", kind="context_changed"),
            ]

        issued_at = datetime.now(UTC)
        pact = ImpactPact(
            pact_id=f"igp_{digest}",
            context_hash=context_hash,
            request=request,
            context=context,
            risk=risk,
            allowed_actions=sorted(set(allowed)),
            blocked_actions=sorted(set(blocked)),
            required_validations=list(dict.fromkeys(validations)),
            requires_human_approval=approvals,
            execution_scope={},
            artifact_hashes=[],
            postconditions=postconditions,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=self.pact_ttl_minutes),
            signature="",
        )
        artifacts = self.generate_artifacts(request, pact)
        hashes = [artifact.sha256 for artifact in artifacts]
        scope = {}
        if "deploy_staging" in pact.allowed_actions:
            scope["deploy_staging"] = {"targets": ["staging"], "artifact_hashes": hashes}
        pact = pact.model_copy(update={"artifact_hashes": hashes, "execution_scope": scope})
        return self.signer.issue(pact)

    @staticmethod
    def _policy_fingerprint(pact: ImpactPact) -> str:
        payload = pact.model_dump(
            mode="json",
            exclude={"signature", "issued_at", "expires_at", "context"},
        )
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def guard(self, pact: ImpactPact, action: str) -> GuardDecision:
        common = {"policy_version": pact.policy_version, "context_hash": pact.context_hash}
        if action in pact.blocked_actions:
            return GuardDecision(
                action=action,
                allowed=False,
                decision=GuardDecisionType.DENY,
                reason=f"Blocked by {pact.risk.tier.value}-risk Impact Pact",
                **common,
            )
        if action in pact.requires_human_approval:
            return GuardDecision(
                action=action,
                allowed=False,
                decision=GuardDecisionType.REQUIRE_APPROVAL,
                reason="Impact Pact requires explicit human approval for this action",
                **common,
            )
        if action in pact.allowed_actions:
            return GuardDecision(
                action=action,
                allowed=True,
                decision=GuardDecisionType.ALLOW,
                reason="Allowed by signed Impact Pact",
                **common,
            )
        return GuardDecision(
            action=action,
            allowed=False,
            decision=GuardDecisionType.DENY,
            reason="Action not present in Pact allowlist",
            **common,
        )

    @staticmethod
    def _artifact(path: str, kind: str, content: str) -> GeneratedArtifact:
        return GeneratedArtifact(
            path=path,
            kind=kind,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            content=content,
        )

    def generate_artifacts(self, request: ChangeRequest, pact: ImpactPact) -> list[GeneratedArtifact]:
        report = (
            "# iGraph Impact Report\n\n"
            f"- Pact: `{pact.pact_id}`\n- Source: `{pact.context.source_urn}`\n"
            f"- Context fingerprint: `{pact.context_hash}`\n"
            f"- Risk: **{pact.risk.tier.value.upper()}** ({pact.risk.score}/100)\n"
            f"- Downstream assets: {len(pact.context.downstream)}\n"
            f"- Retrieval complete: `{pact.context.retrieval_complete}`\n"
            f"- Reasons: {', '.join(pact.risk.reasons)}\n"
        )
        artifacts = [self._artifact("impact-report.md", "report", report)]
        if request.action == "rename_column" and request.field and request.replacement:
            migration = (
                "-- Generated by iGraph for review only.\n"
                f"-- Impact Pact: {pact.pact_id}\n"
                f"ALTER TABLE {request.entity} RENAME COLUMN {request.field} TO {request.replacement};\n"
            )
            regression = (
                "-- iGraph regression check\n"
                f"SELECT {request.replacement} FROM {request.entity} "
                f"WHERE {request.replacement} IS NOT NULL LIMIT 1;\n"
            )
            artifacts += [
                self._artifact("migration.sql", "sql_migration", migration),
                self._artifact("regression-test.sql", "sql_test", regression),
            ]
        return artifacts

    def validate(self, request: ChangeRequest, pact: ImpactPact, artifacts: list[GeneratedArtifact]) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        artifact_kinds = {artifact.kind for artifact in artifacts}
        for name in pact.required_validations:
            if name == "schema_compatibility":
                if request.field and pact.context.schema_fields:
                    exists = request.field in pact.context.schema_fields
                    results.append(
                        ValidationResult(
                            name=name,
                            status=ValidationStatus.PASS if exists else ValidationStatus.FAIL,
                            evidence=f"Field {request.field!r} {'exists' if exists else 'was not found'} in the DataHub schema snapshot.",
                        )
                    )
                else:
                    results.append(
                        ValidationResult(
                            name=name,
                            status=ValidationStatus.PENDING,
                            evidence="Schema fields unavailable; requires execution-time validation.",
                        )
                    )
            elif name == "lineage_recheck":
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.PENDING,
                        evidence=f"Pre-change context fingerprint: {pact.context_hash}. Call /v1/verify after applying the reviewable artifact.",
                    )
                )
            elif name == "dashboard_dependency_check":
                count = sum(node.type.lower() == "dashboard" for node in pact.context.downstream)
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.WARNING if count else ValidationStatus.PASS,
                        evidence=f"{count} downstream dashboard(s) require review.",
                    )
                )
            elif name == "ml_dependency_check":
                count = sum(node.type.lower() in {"ml_feature", "ml_model", "mlfeature", "mlmodel"} for node in pact.context.downstream)
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.WARNING if count else ValidationStatus.PASS,
                        evidence=f"{count} downstream ML asset(s) require review.",
                    )
                )
            elif name == "context_completeness_check":
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.FAIL,
                        evidence="The live context was truncated or explicitly marked incomplete; execution is fail-closed.",
                    )
                )
            else:
                results.append(
                    ValidationResult(name=name, status=ValidationStatus.PENDING, evidence="No deterministic validator registered.")
                )
        if request.action == "rename_column" and "sql_migration" not in artifact_kinds:
            results.append(ValidationResult(name="artifact_generation", status=ValidationStatus.FAIL, evidence="Expected SQL migration was not generated."))
        return results

    @staticmethod
    def _receipt_markdown(pact: ImpactPact, status: str, events: list[ExecutionEvent]) -> str:
        lines = [
            f"# iGraph Change Receipt {pact.pact_id}",
            "",
            f"- Status: `{status}`",
            f"- Context fingerprint: `{pact.context_hash}`",
            f"- Risk: `{pact.risk.tier.value}` ({pact.risk.score}/100)",
            f"- Signature: `{pact.signature}`",
        ]
        for event in events:
            lines.append(f"- Action `{event.action}`: `{event.status.value}` — {event.detail}")
        return "\n".join(lines)

    async def _receipt_for_pact(self, pact: ImpactPact, *, execution_events: list[ExecutionEvent] | None = None) -> ChangeReceipt:
        artifacts = self.generate_artifacts(pact.request, pact)
        validations = self.validate(pact.request, pact, artifacts)
        events = execution_events or []
        failed = any(result.status == ValidationStatus.FAIL for result in validations) or any(event.status == ExecutionStatus.FAILED for event in events)
        unavailable = any(event.status == ExecutionStatus.CONTEXT_UNAVAILABLE for event in events)
        blocked = any(event.status in {ExecutionStatus.DENIED, ExecutionStatus.PACT_STALE} for event in events)
        executed = any(event.status == ExecutionStatus.EXECUTED for event in events)
        status = "context_unavailable" if unavailable else "failed" if failed else "blocked" if blocked else "executed" if executed else "ready_for_review"
        writeback = await self.datahub.writeback(
            pact.context.source_urn,
            pact.pact_id,
            pact.risk.tier.value,
            status,
            pact.context_hash,
            receipt_markdown=self._receipt_markdown(pact, status, events),
        )
        return ChangeReceipt(
            receipt_id=f"receipt_{pact.pact_id.removeprefix('igp_')}",
            pact_id=pact.pact_id,
            status=status,
            context_hash=pact.context_hash,
            attempted_actions=[event.decision for event in events],
            execution_events=events,
            generated_artifacts=artifacts,
            validations=validations,
            writeback=writeback,
        )

    async def analyze(self, request: ChangeRequest) -> AnalysisResponse:
        context = await self.datahub.get_context(request.entity, request.field)
        risk = self.assess_risk(request, context)
        pact = self.make_pact(request, context, risk)
        receipt = await self._receipt_for_pact(pact)
        return AnalysisResponse(pact=pact, receipt=receipt)

    async def _event_for_decision(self, pact: ImpactPact, action: str, decision: GuardDecision, parameters: dict[str, Any], human_approved: bool) -> ExecuteActionResponse:
        event = self.enforcement.execute(
            pact=pact, action=action, decision=decision, parameters=parameters, human_approved=human_approved
        )
        receipt = await self._receipt_for_pact(pact, execution_events=[event])
        return ExecuteActionResponse(pact_id=pact.pact_id, decision=event.decision, event=event, receipt=receipt)

    async def execute_action(self, *, pact: ImpactPact, action: str, parameters: dict[str, Any], human_approved: bool = False) -> ExecuteActionResponse:
        common = {"policy_version": pact.policy_version, "context_hash": pact.context_hash}
        try:
            self.signer.verify(pact)
        except PactSignatureError as exc:
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(action=action, allowed=False, decision=GuardDecisionType.DENY, reason=str(exc), **common),
                parameters,
                human_approved,
            )

        now = datetime.now(UTC)
        if now >= pact.expires_at:
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(action=action, allowed=False, decision=GuardDecisionType.PACT_STALE, reason="Impact Pact has expired and must be recompiled", **common),
                parameters,
                human_approved,
            )

        try:
            current = await self.datahub.get_context(pact.request.entity, pact.request.field)
        except ContextUnavailableError as exc:
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(action=action, allowed=False, decision=GuardDecisionType.CONTEXT_UNAVAILABLE, reason=str(exc), **common),
                parameters,
                human_approved,
            )
        if self.datahub.live_requested and (not current.live or not current.retrieval_complete):
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(
                    action=action,
                    allowed=False,
                    decision=GuardDecisionType.CONTEXT_UNAVAILABLE,
                    reason="Live context was not complete at the enforcement boundary",
                    **common,
                ),
                parameters,
                human_approved,
            )
        current_hash = self.context_hash(current)
        if current_hash != pact.context_hash:
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(action=action, allowed=False, decision=GuardDecisionType.PACT_STALE, reason=f"Context drift detected: Pact {pact.context_hash} != current {current_hash}", **common),
                parameters,
                human_approved,
            )

        current_policy = self.make_pact(pact.request, current, self.assess_risk(pact.request, current))
        if self._policy_fingerprint(current_policy) != self._policy_fingerprint(pact):
            return await self._event_for_decision(
                pact,
                action,
                GuardDecision(action=action, allowed=False, decision=GuardDecisionType.PACT_STALE, reason="Policy or execution scope changed; recompile the Impact Pact", **common),
                parameters,
                human_approved,
            )

        decision = self.guard(pact, action)
        return await self._event_for_decision(pact, action, decision, parameters, human_approved)

    async def verify(self, pact: ImpactPact) -> VerificationResponse:
        try:
            self.signer.verify(pact)
        except PactSignatureError as exc:
            return VerificationResponse(
                pact_id=pact.pact_id,
                pre_context_hash=pact.context_hash,
                post_context_hash=pact.context_hash,
                validations=[ValidationResult(name="pact_signature", status=ValidationStatus.FAIL, evidence=str(exc))],
                verified=False,
            )

        post_context = await self.datahub.get_context(pact.request.entity, pact.request.replacement or pact.request.field)
        post_hash = self.context_hash(post_context)
        validations: list[ValidationResult] = []
        for condition in pact.postconditions:
            if condition.kind == "context_live":
                status = ValidationStatus.PASS if post_context.live else ValidationStatus.PENDING
                evidence = "Post-change context was read from live DataHub." if post_context.live else "Demo context cannot prove a live post-change state."
            elif condition.kind == "field_present":
                present = condition.target in post_context.schema_fields if post_context.schema_fields else None
                status = ValidationStatus.PASS if present is True else ValidationStatus.FAIL if present is False else ValidationStatus.PENDING
                evidence = f"Field {condition.target!r} is {'present' if present else 'absent'} in the post-change schema." if present is not None else "Post-change schema fields were unavailable."
            elif condition.kind == "field_absent":
                absent = condition.target not in post_context.schema_fields if post_context.schema_fields else None
                status = ValidationStatus.PASS if absent is True else ValidationStatus.FAIL if absent is False else ValidationStatus.PENDING
                evidence = f"Field {condition.target!r} is {'absent' if absent else 'still present'} in the post-change schema." if absent is not None else "Post-change schema fields were unavailable."
            else:
                changed = post_hash != pact.context_hash
                status = ValidationStatus.PASS if changed else ValidationStatus.PENDING
                evidence = f"Pre-change {pact.context_hash}; post-change {post_hash}."
            validations.append(ValidationResult(name=condition.name, status=status, evidence=evidence))
        validations.append(
            ValidationResult(
                name="lineage_recheck",
                status=ValidationStatus.PASS if post_context.live and post_context.retrieval_complete else ValidationStatus.PENDING,
                evidence=f"Post-change context fingerprint: {post_hash}; retrieval_complete={post_context.retrieval_complete}.",
            )
        )
        return VerificationResponse(
            pact_id=pact.pact_id,
            pre_context_hash=pact.context_hash,
            post_context_hash=post_hash,
            validations=validations,
            verified=all(result.status == ValidationStatus.PASS for result in validations),
        )

    async def discover(self, query: str = "*") -> DiscoveryResponse:
        contexts = await self.datahub.discover_candidates(query)
        candidates: list[DiscoveryCandidate] = []
        for context in contexts:
            risk = self.assess_risk(ChangeRequest(action="modify_asset", entity=context.source_name), context)
            candidates.append(
                DiscoveryCandidate(
                    urn=context.source_urn,
                    name=context.source_name,
                    downstream_count=len(context.downstream),
                    dashboard_count=sum(node.type.lower() == "dashboard" for node in context.downstream),
                    ml_count=sum(node.type.lower() in {"ml_feature", "ml_model", "mlfeature", "mlmodel"} for node in context.downstream),
                    risk_score=risk.score,
                )
            )
        candidates.sort(key=lambda item: (item.risk_score, item.downstream_count), reverse=True)
        return DiscoveryResponse(live=bool(contexts and contexts[0].live), candidates=candidates[:10])

    def authority_drift_experiment(self) -> AuthorityDriftExperiment:
        request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
        before_context = DataHubContext(
            source_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
            source_name="orders",
            schema_fields=["order_id", "customer_id", "amount"],
            downstream=[ImpactNode(urn="urn:li:dataset:customer_rollup", name="customer_rollup", type="dataset", depth=1)],
            live=False,
        )
        after_context = DataHubContext(
            source_urn=before_context.source_urn,
            source_name="orders",
            schema_fields=before_context.schema_fields,
            owners=["Data Platform", "Revenue Analytics"],
            domains=["Commerce", "Finance"],
            tags=["pii", "production"],
            downstream=[
                *before_context.downstream,
                ImpactNode(urn="urn:li:dashboard:revenue", name="Executive Revenue", type="dashboard", depth=2, domain="Finance"),
                ImpactNode(urn="urn:li:mlModel:churn_v4", name="churn_v4", type="ml_model", depth=2, domain="Growth"),
            ],
            live=False,
        )
        before = self.make_pact(request, before_context, self.assess_risk(request, before_context))
        after = self.make_pact(request, after_context, self.assess_risk(request, after_context))
        tested_action = "deploy_staging"
        before_decision = self.guard(before, tested_action)
        after_decision = self.guard(after, tested_action)
        return AuthorityDriftExperiment(
            request=request,
            before=before,
            after=after,
            tested_action=tested_action,
            before_decision=before_decision,
            after_decision=after_decision,
            delta=AuthorityDelta(
                newly_allowed=sorted(set(after.allowed_actions) - set(before.allowed_actions)),
                newly_blocked=sorted(set(after.blocked_actions) - set(before.blocked_actions)),
                newly_requires_approval=sorted(set(after.requires_human_approval) - set(before.requires_human_approval)),
            ),
            claim="The request, agent capability and executor are unchanged; authority changes because the organizational context changed.",
        )
