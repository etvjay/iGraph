import asyncio

from igraph.datahub_adapter import DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.executor import EnforcementPoint
from igraph.models import (
    ChangeRequest,
    DataHubContext,
    ExecutionStatus,
    ImpactNode,
    RiskTier,
    ValidationStatus,
)


def test_high_risk_change_blocks_production():
    engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(
        action="rename_column",
        entity="orders",
        field="customer_id",
        replacement="account_id",
    )
    context = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        schema_fields=["customer_id"],
        downstream=[
            ImpactNode(urn="urn:li:dashboard:test", name="Revenue", type="dashboard", depth=1),
            ImpactNode(urn="urn:li:mlFeature:test", name="Churn", type="ml_feature", depth=2),
        ],
    )
    risk = engine.assess_risk(request, context)
    pact = engine.make_pact(request, context, risk)
    decision = engine.guard(pact, "deploy_production")

    assert risk.tier in {RiskTier.HIGH, RiskTier.CRITICAL}
    assert decision.allowed is False
    assert "deploy_production" in pact.blocked_actions


def test_unknown_action_defaults_to_denied():
    engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(action="modify_asset", entity="orders")
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders")
    risk = engine.assess_risk(request, context)
    pact = engine.make_pact(request, context, risk)

    assert engine.guard(pact, "rotate_credentials").allowed is False


def test_rename_generates_real_sql_artifacts():
    engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(
        action="rename_column",
        entity="orders",
        field="customer_id",
        replacement="account_id",
    )
    context = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        schema_fields=["customer_id"],
    )
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    artifacts = engine.generate_artifacts(request, pact)

    migration = next(item for item in artifacts if item.kind == "sql_migration")
    assert "RENAME COLUMN customer_id TO account_id" in migration.content
    assert len(migration.sha256) == 64


def test_lineage_validation_is_not_faked():
    engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(
        action="rename_column",
        entity="orders",
        field="customer_id",
        replacement="account_id",
    )
    context = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        schema_fields=["customer_id"],
    )
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    results = engine.validate(request, pact, engine.generate_artifacts(request, pact))

    lineage = next(result for result in results if result.name == "lineage_recheck")
    schema = next(result for result in results if result.name == "schema_compatibility")
    assert lineage.status == ValidationStatus.PENDING
    assert schema.status == ValidationStatus.PASS


def test_denied_action_never_invokes_executor():
    invoked = {"count": 0}

    def production_executor(_parameters):
        invoked["count"] += 1
        return {"status": "should-not-run"}

    enforcement = EnforcementPoint(executors={"deploy_production": production_executor})
    engine = ImpactEngine(DataHubAdapter(), enforcement=enforcement)
    request = ChangeRequest(
        action="rename_column",
        entity="orders",
        field="customer_id",
        replacement="account_id",
    )
    context = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        schema_fields=["customer_id"],
        tags=["pii"],
        downstream=[
            ImpactNode(urn="urn:li:dashboard:test", name="Revenue", type="dashboard", depth=1)
        ],
    )
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    decision = engine.guard(pact, "deploy_production")
    event = enforcement.execute(
        pact=pact,
        action="deploy_production",
        decision=decision,
        parameters={},
    )

    assert event.status == ExecutionStatus.DENIED
    assert event.executor_invoked is False
    assert invoked["count"] == 0


def test_same_request_gets_less_authority_when_context_changes():
    engine = ImpactEngine(DataHubAdapter())
    experiment = engine.authority_drift_experiment()

    assert experiment.before_decision.allowed is True
    assert experiment.after_decision.allowed is False
    assert experiment.tested_action == "deploy_staging"
    assert "deploy_staging" in experiment.delta.newly_blocked
    assert experiment.before.context_hash != experiment.after.context_hash
    assert experiment.request == experiment.before.request == experiment.after.request


def test_low_risk_allowed_action_reaches_registered_executor():
    invoked = {"count": 0}

    def staging_executor(parameters):
        invoked["count"] += 1
        return {"status": "ok", "target": parameters["target"]}

    enforcement = EnforcementPoint(executors={"deploy_staging": staging_executor})
    engine = ImpactEngine(DataHubAdapter(), enforcement=enforcement)
    request = ChangeRequest(
        action="rename_column",
        entity="orders",
        field="customer_id",
        replacement="account_id",
    )
    context = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        schema_fields=["customer_id"],
    )
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    decision = engine.guard(pact, "deploy_staging")
    event = enforcement.execute(
        pact=pact,
        action="deploy_staging",
        decision=decision,
        parameters={"target": "sandbox"},
    )

    assert decision.allowed is True
    assert event.status == ExecutionStatus.EXECUTED
    assert event.executor_invoked is True
    assert event.evidence_sha256 is not None
    assert invoked["count"] == 1
