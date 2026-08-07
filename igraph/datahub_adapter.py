from __future__ import annotations

import os
from typing import Any

import httpx

from igraph.models import DataHubContext, ImpactNode


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
    """Thin DataHub GraphQL adapter with a deterministic demo fallback.

    The hackathon project can run against DataHub OSS by setting DATAHUB_GMS_URL
    and optionally DATAHUB_TOKEN. If an entity cannot be resolved, the adapter
    returns a showcase-shaped context so the end-to-end guardrail flow remains
    demonstrable without external credentials.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("DATAHUB_GMS_URL", "").rstrip("/")
        self.token = os.getenv("DATAHUB_TOKEN")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def get_context(self, entity: str) -> DataHubContext:
        if self.configured:
            try:
                result = await self._graphql_context(entity)
                if result:
                    return result
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                pass
        return self._demo_context(entity)

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.base_url}/api/graphql",
                headers=headers,
                json={"query": query, "variables": variables},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise ValueError(payload["errors"])
            return payload["data"]

    async def _graphql_context(self, entity: str) -> DataHubContext | None:
        search_query = """
        query Search($input: SearchInput!) {
          search(input: $input) {
            searchResults { entity { urn type ... on Dataset { name description } } }
          }
        }
        """
        data = await self._graphql(
            search_query,
            {"input": {"type": "DATASET", "query": entity, "start": 0, "count": 1}},
        )
        results = data.get("search", {}).get("searchResults", [])
        if not results:
            return None
        source = results[0]["entity"]
        urn = source["urn"]

        lineage_query = """
        query EntityLineage($urn: String!, $direction: LineageDirection!) {
          entity(urn: $urn) {
            urn
            ... on Dataset { name description }
            downstream: lineage(input: {direction: $direction, start: 0, count: 50}) {
              relationships {
                degree
                entity { urn type ... on Dataset { name } ... on Dashboard { urn } }
              }
            }
          }
        }
        """
        lineage = await self._graphql(lineage_query, {"urn": urn, "direction": "DOWNSTREAM"})
        root = lineage.get("entity") or {}
        rels = ((root.get("downstream") or {}).get("relationships") or [])
        downstream: list[ImpactNode] = []
        for rel in rels:
            child = rel.get("entity") or {}
            downstream.append(
                ImpactNode(
                    urn=child.get("urn", "unknown"),
                    name=child.get("name") or child.get("urn", "unknown").split(",")[-1].rstrip(")"),
                    type=str(child.get("type", "unknown")).lower(),
                    depth=int(rel.get("degree") or 1),
                )
            )

        return DataHubContext(
            source_urn=urn,
            source_name=root.get("name") or source.get("name") or entity,
            downstream=downstream,
            description=root.get("description") or source.get("description"),
            live=True,
        )

    def _demo_context(self, entity: str) -> DataHubContext:
        return DataHubContext(
            source_urn=f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{entity},PROD)",
            source_name=entity,
            owners=["Data Platform"],
            domains=["Commerce"],
            tags=["production", "customer-data"],
            downstream=DEMO_DOWNSTREAM,
            assertions=["schema_compatibility", "freshness_sla"],
            description="Demo context shaped after DataHub showcase-ecommerce metadata.",
            live=False,
        )

    async def writeback(self, urn: str, pact_id: str, risk: str, status: str) -> dict[str, str]:
        # Write-back is deliberately represented as an auditable payload first.
        # The next integration milestone can emit this as DataHub structured
        # properties/tags through the SDK once the target OSS instance is fixed.
        return {
            "target_urn": urn,
            "igraph_pact_id": pact_id,
            "igraph_risk": risk,
            "igraph_status": status,
            "mode": "prepared" if self.configured else "demo",
        }
