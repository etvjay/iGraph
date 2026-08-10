from datetime import UTC, datetime, timedelta

import pytest

from igraph.datahub_adapter import ContextUnavailableError, DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.executor import EnforcementPoint
from igraph.models import (
    ChangeRequest,
    DataHubContext,
    ExecutionStatus,
    GuardDecisionType,
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
            ImpactNode(
                urn="urn:li:dashboard:test",
                name="Revenue",
                type="dashboard",
                depth=1,
            ),
            ImpactNode(
                urn="urn:li:mlFeature:test",
                name="Churn",
                type="ml_feature",
                depth=2,
            ),
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
            ImpactNode(
                urn="urn:li:dashboard:test",
                name="Revenue",
                type="dashboard",
                depth=1,
            )
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
        parameters={"target": "staging", "artifact_sha256": pact.artifact_hashes[0]},
    )

    assert decision.allowed is True
    assert event.status == ExecutionStatus.EXECUTED
    assert event.executor_invoked is True
    assert event.evidence_sha256 is not None
    assert invoked["count"] == 1


class StaticAdapter:
    """Small adapter fixture for execution/verification tests."""

    configured = False
    live_requested = False
    emit_writeback = False

    def __init__(self, context=None, error=None):
        self.context = context
        self.error = error

    async def get_context(self, _entity, _field=None):
        if self.error:
            raise self.error
        return self.context

    async def writeback(self, urn, pact_id, risk, status, context_hash, receipt_markdown=None):
        from igraph.models import DataHubWriteback

        return DataHubWriteback(target_urn=urn, mode="demo", properties={"igraph.pact_id": pact_id})


def test_context_hash_is_stable_when_datahub_lists_are_reordered():
    engine = ImpactEngine(DataHubAdapter())
    first = DataHubContext(
        source_urn="urn:li:dataset:test",
        source_name="orders",
        owners=["b", "a"],
        tags=["z", "a"],
        downstream=[ImpactNode(urn="2", name="two", type="dataset"), ImpactNode(urn="1", name="one", type="dashboard")],
    )
    second = first.model_copy(deep=True, update={"owners": ["a", "b"], "tags": ["a", "z"], "downstream": list(reversed(first.downstream))})
    assert engine.context_hash(first) == engine.context_hash(second)


def test_live_context_failure_is_not_replaced_with_demo(monkeypatch):
    monkeypatch.setenv("IGRAPH_CONTEXT_MODE", "live")
    monkeypatch.delenv("DATAHUB_GMS_URL", raising=False)
    adapter = DataHubAdapter()

    async def read():
        await adapter.get_context("orders")

    with pytest.raises(ContextUnavailableError):
        import asyncio

        asyncio.run(read())


def test_live_engine_requires_non_default_signing_secret(monkeypatch):
    monkeypatch.setenv("IGRAPH_CONTEXT_MODE", "live")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://localhost:8080")
    monkeypatch.delenv("IGRAPH_SIGNING_SECRET", raising=False)

    with pytest.raises(ValueError, match="IGRAPH_SIGNING_SECRET"):
        ImpactEngine(DataHubAdapter())


@pytest.mark.asyncio
async def test_tampered_pact_is_denied_before_executor():
    invoked = {"count": 0}

    def executor(_parameters):
        invoked["count"] += 1
        return {"status": "bad"}

    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    adapter = StaticAdapter(context=context)
    engine = ImpactEngine(adapter, enforcement=EnforcementPoint({"deploy_staging": executor}))
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    tampered = pact.model_copy(update={"allowed_actions": [*pact.allowed_actions, "deploy_production"]})

    result = await engine.execute_action(
        pact=tampered,
        action="deploy_staging",
        parameters={"target": "staging", "artifact_sha256": pact.artifact_hashes[0]},
    )

    assert result.event.status == ExecutionStatus.DENIED
    assert result.decision.decision == GuardDecisionType.DENY
    assert result.event.executor_invoked is False
    assert invoked["count"] == 0


@pytest.mark.asyncio
async def test_expired_signed_pact_is_stale():
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    adapter = StaticAdapter(context=context)
    engine = ImpactEngine(adapter)
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    expired = pact.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)})
    expired = engine.signer.issue(expired)

    result = await engine.execute_action(pact=expired, action="create_patch", parameters={})

    assert result.event.status == ExecutionStatus.PACT_STALE
    assert result.event.executor_invoked is False


def test_execution_parameters_cannot_escape_signed_scope():
    engine = ImpactEngine(DataHubAdapter())
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    decision = engine.guard(pact, "deploy_staging")
    event = engine.enforcement.execute(
        pact=pact,
        action="deploy_staging",
        decision=decision,
        parameters={"target": "production", "artifact_sha256": pact.artifact_hashes[0]},
    )

    assert event.status == ExecutionStatus.DENIED
    assert event.executor_invoked is False


def test_signed_pact_cannot_be_replayed_after_executor_invocation():
    invoked = {"count": 0}

    def staging_executor(_parameters):
        invoked["count"] += 1
        return {"status": "ok"}

    enforcement = EnforcementPoint({"deploy_staging": staging_executor})
    engine = ImpactEngine(enforcement=enforcement, datahub=DataHubAdapter())
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    decision = engine.guard(pact, "deploy_staging")
    parameters = {"target": "staging", "artifact_sha256": pact.artifact_hashes[0]}

    first = enforcement.execute(pact=pact, action="deploy_staging", decision=decision, parameters=parameters)
    second = enforcement.execute(pact=pact, action="deploy_staging", decision=decision, parameters=parameters)

    assert first.status == ExecutionStatus.EXECUTED
    assert second.status == ExecutionStatus.DENIED
    assert second.executor_invoked is False
    assert invoked["count"] == 1


@pytest.mark.asyncio
async def test_context_unavailable_blocks_execution_and_executor():
    invoked = {"count": 0}

    def executor(_parameters):
        invoked["count"] += 1
        return {"status": "bad"}

    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    planning_engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = planning_engine.make_pact(request, context, planning_engine.assess_risk(request, context))
    engine = ImpactEngine(
        StaticAdapter(error=ContextUnavailableError("GMS timeout")),
        enforcement=EnforcementPoint({"deploy_staging": executor}),
        signer=planning_engine.signer,
    )

    result = await engine.execute_action(
        pact=pact,
        action="deploy_staging",
        parameters={"target": "staging", "artifact_sha256": pact.artifact_hashes[0]},
    )

    assert result.event.status == ExecutionStatus.CONTEXT_UNAVAILABLE
    assert result.event.executor_invoked is False
    assert invoked["count"] == 0


@pytest.mark.asyncio
async def test_live_postconditions_are_required_for_verification():
    pre = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"], live=True)
    post = pre.model_copy(update={"schema_fields": ["account_id"], "live": True})
    planning_engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    pact = planning_engine.make_pact(request, pre, planning_engine.assess_risk(request, pre))
    engine = ImpactEngine(StaticAdapter(context=post), signer=planning_engine.signer)

    result = await engine.verify(pact)

    assert result.verified is True
    assert result.post_context_hash != result.pre_context_hash
