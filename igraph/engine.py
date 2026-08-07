from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from igraph.datahub_adapter import DataHubAdapter
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
    ExecutionStatus,
    GeneratedArtifact,
    GuardDecision,
    ImpactNode,
    ImpactPact,
    RiskAssessment,
    RiskTier,
    ValidationResult,
    ValidationStatus,
    VerificationResponse,
)


@dataclass(slots=True)
class ImpactEngine:
    datahub: DataHubAdapter
    enforcement: EnforcementPoint = field(default_factory=default_enforcement_point)

    @staticmethod
    def context_hash(context) -> str:
        payload = context.model_dump(mode="json")
        payload.pop("live", None)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def assess_risk(self, request: ChangeRequest, context) -> RiskAssessment:
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

        types = {node.type for node in context.downstream}
        if "dashboard" in types:
            score += 20
            reasons.append("production_dashboard_dependency")
        if {"ml_feature", "ml_model"} & types:
            score += 25
            reasons.append("ml_dependency_detected")
        if len(context.domains) > 1 or len({node.domain for node in context.downstream if node.domain}) > 1:
            score += 12
            reasons.append("cross_domain_change")
        if request.action in {"drop_column", "change_type"}:
            score += 25
            reasons.append("breaking_schema_change")
        if any(tag.lower() in {"pii", "sensitive", "restricted"} for tag in context.tags):
            score += 30
            reasons.append("sensitive_data_classification")

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

    def make_pact(self, request: ChangeRequest, context, risk: RiskAssessment) -> ImpactPact:
        context_hash = self.context_hash(context)
        digest = hashlib.sha256(
            f"{context.source_urn}:{context_hash}:{request.model_dump_json()}".encode()
        ).hexdigest()[:12]
        allowed = ["inspect_context", "generate_migration", "generate_tests", "create_patch"]
        blocked = ["delete_dataset", "alter_unrelated_schema"]
        approvals: list[str] = []

        # Reversible staging execution is granted only when the current context is
        # low/medium risk. High-consequence context removes that authority.
        if risk.tier in {RiskTier.LOW, RiskTier.MEDIUM}:
            allowed.append("deploy_staging")
        else:
            blocked.extend(["deploy_staging", "deploy_production"])
            approvals.append("deploy_production")

        validations = ["schema_compatibility", "lineage_recheck"]
        if any(node.type == "dashboard" for node in context.downstream):
            validations.append("dashboard_dependency_check")
        if any(node.type in {"ml_feature", "ml_model"} for node in context.downstream):
            validations.append("ml_dependency_check")

        return ImpactPact(
            pact_id=f"igp_{digest}",
            context_hash=context_hash,
            request=request,
            context=context,
            risk=risk,
            allowed_actions=sorted(set(allowed)),
            blocked_actions=sorted(set(blocked)),
            required_validations=validations,
            requires_human_approval=approvals,
        )

    def guard(self, pact: ImpactPact, action: str) -> GuardDecision:
        if action in pact.blocked_actions:
            return GuardDecision(
                action=action,
                allowed=False,
                reason=f"Blocked by {pact.risk.tier.value}-risk Impact Pact",
            )
        if action in pact.allowed_actions:
            return GuardDecision(action=action, allowed=True, reason="Allowed by Impact Pact")
        return GuardDecision(
            action=action,
            allowed=False,
            reason="Action not present in Pact allowlist",
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

    def validate(
        self,
        request: ChangeRequest,
        pact: ImpactPact,
        artifacts: list[GeneratedArtifact],
    ) -> list[ValidationResult]:
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
                            evidence=(
                                f"Field {request.field!r} "
                                f"{'exists' if exists else 'was not found'} in the DataHub schema snapshot."
                            ),
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
                        evidence=(
                            f"Pre-change context fingerprint: {pact.context_hash}. "
                            "Call /v1/verify after applying the reviewable artifact."
                        ),
                    )
                )
            elif name == "dashboard_dependency_check":
                count = sum(node.type == "dashboard" for node in pact.context.downstream)
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.WARNING if count else ValidationStatus.PASS,
                        evidence=f"{count} downstream dashboard(s) require review.",
                    )
                )
            elif name == "ml_dependency_check":
                count = sum(
                    node.type in {"ml_feature", "ml_model"} for node in pact.context.downstream
                )
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.WARNING if count else ValidationStatus.PASS,
                        evidence=f"{count} downstream ML asset(s) require review.",
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        name=name,
                        status=ValidationStatus.PENDING,
                        evidence="No deterministic validator registered.",
                    )
                )
        if request.action == "rename_column" and "sql_migration" not in artifact_kinds:
            results.append(
                ValidationResult(
                    name="artifact_generation",
                    status=ValidationStatus.FAIL,
                    evidence="Expected SQL migration was not generated.",
                )
            )
        return results

    async def _receipt_for_pact(
        self,
        pact: ImpactPact,
        *,
        execution_events=None,
    ) -> ChangeReceipt:
        artifacts = self.generate_artifacts(pact.request, pact)
        validations = self.validate(pact.request, pact, artifacts)
        execution_events = execution_events or []
        failed = any(result.status == ValidationStatus.FAIL for result in validations) or any(
            event.status == ExecutionStatus.FAILED for event in execution_events
        )
        blocked = any(event.status == ExecutionStatus.DENIED for event in execution_events)
        status = "failed" if failed else "blocked" if blocked else "ready_for_review"
        writeback = await self.datahub.writeback(
            pact.context.source_urn,
            pact.pact_id,
            pact.risk.tier.value,
            status,
            pact.context_hash,
        )
        return ChangeReceipt(
            receipt_id=f"receipt_{pact.pact_id.removeprefix('igp_')}",
            pact_id=pact.pact_id,
            status=status,
            attempted_actions=[event.decision for event in execution_events],
            execution_events=execution_events,
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

    async def execute_action(
        self,
        *,
        pact: ImpactPact,
        action: str,
        parameters: dict,
        human_approved: bool = False,
    ) -> ExecuteActionResponse:
        # A Pact is bound to the context fingerprint that produced it. Re-read live
        # context before execution and fail closed if reality has changed underneath it.
        current = await self.datahub.get_context(pact.request.entity, pact.request.field)
        if current.live:
            current_hash = self.context_hash(current)
            if current_hash != pact.context_hash:
                drift_decision = GuardDecision(
                    action=action,
                    allowed=False,
                    reason=(
                        "Context drift detected: Impact Pact is stale and must be recompiled "
                        f"({pact.context_hash} != {current_hash})"
                    ),
                )
                event = self.enforcement.execute(
                    pact=pact,
                    action=action,
                    decision=drift_decision,
                    parameters=parameters,
                    human_approved=human_approved,
                )
                receipt = await self._receipt_for_pact(pact, execution_events=[event])
                return ExecuteActionResponse(
                    pact_id=pact.pact_id,
                    decision=event.decision,
                    event=event,
                    receipt=receipt,
                )

        decision = self.guard(pact, action)
        event = self.enforcement.execute(
            pact=pact,
            action=action,
            decision=decision,
            parameters=parameters,
            human_approved=human_approved,
        )
        receipt = await self._receipt_for_pact(pact, execution_events=[event])
        return ExecuteActionResponse(
            pact_id=pact.pact_id,
            decision=event.decision,
            event=event,
            receipt=receipt,
        )

    async def verify(self, pact: ImpactPact) -> VerificationResponse:
        post_context = await self.datahub.get_context(
            pact.request.entity, pact.request.replacement or pact.request.field
        )
        post_hash = self.context_hash(post_context)
        validations = [
            ValidationResult(
                name="lineage_recheck",
                status=ValidationStatus.PASS if post_context.live else ValidationStatus.PENDING,
                evidence=(
                    f"Re-read live DataHub context after the proposed change; fingerprint {post_hash}."
                    if post_context.live
                    else "Live DataHub is not configured; post-change graph verification is pending."
                ),
            )
        ]
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
            risk = self.assess_risk(
                ChangeRequest(action="modify_asset", entity=context.source_name), context
            )
            candidates.append(
                DiscoveryCandidate(
                    urn=context.source_urn,
                    name=context.source_name,
                    downstream_count=len(context.downstream),
                    dashboard_count=sum(
                        node.type == "dashboard" for node in context.downstream
                    ),
                    ml_count=sum(
                        node.type in {"ml_feature", "ml_model"}
                        for node in context.downstream
                    ),
                    risk_score=risk.score,
                )
            )
        candidates.sort(key=lambda item: (item.risk_score, item.downstream_count), reverse=True)
        return DiscoveryResponse(
            live=bool(contexts and contexts[0].live), candidates=candidates[:10]
        )

    def authority_drift_experiment(self) -> AuthorityDriftExperiment:
        """Deterministic proof fixture for the product's central claim.

        The request and executor remain identical. Only organizational context changes.
        The resulting authority changes with it.
        """
        request = ChangeRequest(
            action="rename_column",
            entity="orders",
            field="customer_id",
            replacement="account_id",
        )
        before_context = DataHubContext(
            source_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
            source_name="orders",
            schema_fields=["order_id", "customer_id", "amount"],
            downstream=[
                ImpactNode(
                    urn="urn:li:dataset:customer_rollup",
                    name="customer_rollup",
                    type="dataset",
                    depth=1,
                )
            ],
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
                ImpactNode(
                    urn="urn:li:dashboard:revenue",
                    name="Executive Revenue",
                    type="dashboard",
                    depth=2,
                    domain="Finance",
                ),
                ImpactNode(
                    urn="urn:li:mlModel:churn_v4",
                    name="churn_v4",
                    type="ml_model",
                    depth=2,
                    domain="Growth",
                ),
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
                newly_requires_approval=sorted(
                    set(after.requires_human_approval) - set(before.requires_human_approval)
                ),
            ),
            claim=(
                "The request, agent capability and executor are unchanged; authority changes "
                "because the organizational context changed."
            ),
        )
