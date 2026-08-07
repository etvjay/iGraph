from igraph.datahub_adapter import DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.models import ChangeRequest, DataHubContext, ImpactNode, RiskTier, ValidationStatus


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
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    artifacts = engine.generate_artifacts(request, pact)

    migration = next(item for item in artifacts if item.kind == "sql_migration")
    assert "RENAME COLUMN customer_id TO account_id" in migration.content
    assert len(migration.sha256) == 64


def test_lineage_validation_is_not_faked():
    engine = ImpactEngine(DataHubAdapter())
    request = ChangeRequest(action="rename_column", entity="orders", field="customer_id", replacement="account_id")
    context = DataHubContext(source_urn="urn:li:dataset:test", source_name="orders", schema_fields=["customer_id"])
    pact = engine.make_pact(request, context, engine.assess_risk(request, context))
    results = engine.validate(request, pact, engine.generate_artifacts(request, pact))

    lineage = next(result for result in results if result.name == "lineage_recheck")
    schema = next(result for result in results if result.name == "schema_compatibility")
    assert lineage.status == ValidationStatus.PENDING
    assert schema.status == ValidationStatus.PASS
