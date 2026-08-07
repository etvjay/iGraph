from __future__ import annotations

import os

from datahub.metadata.urns import Urn
from datahub.sdk import DataHubClient

from igraph.models import DataHubContext, DataHubWriteback, ImpactNode


DEMO_DOWNSTREAM = [
    ImpactNode(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,customer_ltv,PROD)",
        name="customer_ltv",
        type="dataset",
        depth=1,
        owner="Data Platform",
        domain="Commerce",
    ),
    ImpactNode(
        urn="urn:li:dashboard:(looker,revenue_overview)",
        name="Revenue Overview",
        type="dashboard",
        depth=2,
        owner="Revenue Analytics",
        domain="Finance",
    ),
    ImpactNode(
        urn="urn:li:mlFeature:(churn_features,customer_id)",
        name="churn_features.customer_id",
        type="ml_feature",
        depth=2,
        owner="ML Platform",
        domain="Growth",
    ),
]


class DataHubAdapter:
    """DataHub adapter with live SDK reads/writeback and deterministic demo fallback."""

    def __init__(self) -> None:
        self.base_url = os.getenv("DATAHUB_GMS_URL", "").rstrip("/")
        self.token = os.getenv("DATAHUB_TOKEN") or os.getenv("DATAHUB_GMS_TOKEN")
        self.emit_writeback = os.getenv("IGRAPH_ENABLE_WRITEBACK", "false").lower() == "true"

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _client(self) -> DataHubClient:
        if not self.configured:
            raise RuntimeError("DataHub is not configured")
        return DataHubClient(server=self.base_url, token=self.token)

    async def get_context(self, entity: str, field: str | None = None) -> DataHubContext:
        if self.configured:
            try:
                result = await self._live_context(entity, field)
                if result:
                    return result
            except Exception:
                # Demo fallback is explicitly marked live=False, so a connection
                # problem can never be mistaken for verified DataHub context.
                pass
        return self._demo_context(entity)

    async def _live_context(self, entity: str, field: str | None) -> DataHubContext | None:
        client = self._client()
        if entity.startswith("urn:li:dataset:"):
            parsed = Urn.from_string(entity)
            dataset_urn = parsed if parsed.entity_type == "dataset" else None
        else:
            urns = list(client.search.get_urns(query=entity))
            dataset_urn = next((urn for urn in urns if urn.entity_type == "dataset"), None)
        if dataset_urn is None:
            return None

        dataset = client.entities.get(dataset_urn)
        lineage = client.lineage.get_lineage(
            source_urn=dataset_urn,
            source_column=field,
            direction="downstream",
            max_hops=3,
            count=500,
        )
        downstream = [
            ImpactNode(
                urn=result.urn,
                name=result.name or result.urn,
                type=str(result.type).lower(),
                depth=result.hops,
            )
            for result in lineage
        ]

        owners = [str(owner.owner) for owner in (getattr(dataset, "owners", None) or [])]
        domain = getattr(dataset, "domain", None)
        domains = [str(domain)] if domain else []
        tags = [str(tag.tag).split(":")[-1] for tag in (getattr(dataset, "tags", None) or [])]

        schema_fields: list[str] = []
        schema = getattr(dataset, "schema", None)
        if schema:
            try:
                schema_fields = [column.field_path for column in schema]
            except TypeError:
                pass

        assertions: list[str] = []
        try:
            for assertion in client.assertions.get_assertions_for_entity(dataset_urn):
                assertions.append(str(getattr(assertion, "urn", assertion)))
        except Exception:
            pass

        source_name = getattr(dataset, "display_name", None) or getattr(dataset_urn, "name", None)
        return DataHubContext(
            source_urn=str(dataset_urn),
            source_name=source_name or str(dataset_urn),
            schema_fields=schema_fields,
            owners=owners,
            domains=domains,
            tags=tags,
            downstream=downstream,
            assertions=assertions,
            description=getattr(dataset, "description", None),
            live=True,
        )

    def _demo_context(self, entity: str) -> DataHubContext:
        return DataHubContext(
            source_urn=f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{entity},PROD)",
            source_name=entity,
            schema_fields=["order_id", "customer_id", "created_at", "amount"],
            owners=["Data Platform"],
            domains=["Commerce"],
            tags=["production", "customer-data"],
            downstream=DEMO_DOWNSTREAM,
            assertions=["schema_compatibility", "freshness_sla"],
            description="Deterministic context shaped after the DataHub showcase-ecommerce graph.",
            live=False,
        )

    async def writeback(
        self,
        urn: str,
        pact_id: str,
        risk: str,
        status: str,
        context_hash: str,
    ) -> DataHubWriteback:
        properties = {
            "igraph.pact_id": pact_id,
            "igraph.risk": risk,
            "igraph.status": status,
            "igraph.context_hash": context_hash,
        }
        if not self.configured:
            return DataHubWriteback(target_urn=urn, mode="demo", properties=properties)
        if not self.emit_writeback:
            return DataHubWriteback(target_urn=urn, mode="skipped", properties=properties)

        try:
            client = self._client()
            entity = client.entities.get(Urn.from_string(urn))
            current = dict(getattr(entity, "custom_properties", {}) or {})
            current.update(properties)
            entity.set_custom_properties(current)
            client.entities.update(entity)
            return DataHubWriteback(target_urn=urn, mode="emitted", properties=properties)
        except Exception as exc:
            return DataHubWriteback(
                target_urn=urn,
                mode="failed",
                properties=properties,
                error=str(exc),
            )

    async def discover_candidates(self, query: str = "*") -> list[DataHubContext]:
        if not self.configured:
            return [self._demo_context("orders")]
        client = self._client()
        contexts: list[DataHubContext] = []
        for urn in list(client.search.get_urns(query=query))[:30]:
            if urn.entity_type != "dataset":
                continue
            context = await self.get_context(str(urn))
            if context.live:
                contexts.append(context)
        return contexts
