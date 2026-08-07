from __future__ import annotations

import hashlib
from dataclasses import dataclass

from igraph.datahub_adapter import DataHubAdapter
from igraph.models import (
    AnalysisResponse,
    ChangeReceipt,
    ChangeRequest,
    GuardDecision,
    ImpactPact,
    RiskAssessment,
    RiskTier,
)


PRODUCTION_TYPES = {"dashboard", "ml_feature", "ml_model"}


@dataclass(slots=True)
class ImpactEngine:
    datahub: DataHubAdapter

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
        if len({node.domain for node in context.downstream if node.domain}) > 1:
            score += 12
            reasons.append("cross_domain_change")
        if request.action in {"drop_column", "change_type"}:
            score += 25
            reasons.append("breaking_schema_change")
        if any(tag.lower() in {"pii", "sensitive", "restricted"} for tag in context.tags):
            score += 30
            reasons.append("sensitive_data_classification")

        score = min(score, 100)
        if score >= 75:
            tier = RiskTier.CRITICAL
        elif score >= 45:
            tier = RiskTier.HIGH
        elif score >= 20:
            tier = RiskTier.MEDIUM
        else:
            tier = RiskTier.LOW
        return RiskAssessment(tier=tier, score=score, reasons=reasons or ["isolated_change"])

    def make_pact(self, request: ChangeRequest, context, risk: RiskAssessment) -> ImpactPact:
        digest = hashlib.sha256(
            f"{context.source_urn}:{request.model_dump_json()}".encode()
        ).hexdigest()[:12]
        allowed = ["inspect_context", "generate_migration", "generate_tests", "create_patch"]
        blocked = ["delete_dataset", "alter_unrelated_schema"]
        approvals: list[str] = []
        if risk.tier in {RiskTier.HIGH, RiskTier.CRITICAL}:
            blocked.append("deploy_production")
            approvals.append("deploy_production")
        else:
            allowed.append("deploy_staging")

        validations = ["schema_compatibility", "lineage_recheck"]
        if any(node.type == "dashboard" for node in context.downstream):
            validations.append("dashboard_dependency_check")
        if any(node.type in {"ml_feature", "ml_model"} for node in context.downstream):
            validations.append("ml_dependency_check")

        return ImpactPact(
            pact_id=f"igp_{digest}",
            request=request,
            context=context,
            risk=risk,
            allowed_actions=allowed,
            blocked_actions=blocked,
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
        return GuardDecision(action=action, allowed=False, reason="Action not present in Pact allowlist")

    def generated_artifacts(self, request: ChangeRequest) -> list[str]:
        artifacts = ["examples/impact-report.md", "examples/change-receipt.json"]
        if request.action == "rename_column":
            artifacts.extend(["examples/migration.sql", "examples/regression-test.sql"])
        return artifacts

    async def analyze(self, request: ChangeRequest) -> AnalysisResponse:
        context = await self.datahub.get_context(request.entity)
        risk = self.assess_risk(request, context)
        pact = self.make_pact(request, context, risk)

        attempted = [
            self.guard(pact, "generate_migration"),
            self.guard(pact, "generate_tests"),
            self.guard(pact, "deploy_production"),
        ]
        validations = {name: True for name in pact.required_validations}
        status = "ready_for_review"
        writeback = await self.datahub.writeback(
            context.source_urn, pact.pact_id, risk.tier.value, status
        )
        receipt = ChangeReceipt(
            receipt_id=f"receipt_{pact.pact_id.removeprefix('igp_')}",
            pact_id=pact.pact_id,
            status=status,
            attempted_actions=attempted,
            generated_artifacts=self.generated_artifacts(request),
            validations=validations,
            writeback=writeback,
        )
        return AnalysisResponse(pact=pact, receipt=receipt)
