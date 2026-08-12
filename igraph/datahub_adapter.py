from __future__ import annotations

import os
from typing import Any

try:
    from datahub.metadata.urns import Urn
    from datahub.sdk import DataHubClient
    from datahub.sdk import FilterDsl as SearchFilter
except ImportError:  # pragma: no cover - demo/test environments may omit the SDK
    Urn = None
    DataHubClient = Any  # type: ignore[misc,assignment]
    SearchFilter = None

from igraph.models import DataHubContext, DataHubWriteback, ImpactNode

try:  # Agent Context Kit is optional for importing the demo-only package.
    from datahub_agent_context.context import DataHubContext as AgentDataHubContext
    from datahub_agent_context.mcp_tools import (
        get_dataset_assertions as agent_get_dataset_assertions,
    )
    from datahub_agent_context.mcp_tools import (
        get_dataset_queries as agent_get_dataset_queries,
    )
    from datahub_agent_context.mcp_tools import (
        get_entities as agent_get_entities,
    )
    from datahub_agent_context.mcp_tools import (
        get_lineage as agent_get_lineage,
    )
    from datahub_agent_context.mcp_tools import (
        list_schema_fields as agent_list_schema_fields,
    )
    from datahub_agent_context.mcp_tools import (
        save_document as agent_save_document,
    )
except ImportError:  # pragma: no cover - exercised only without the optional package
    AgentDataHubContext = None
    agent_get_dataset_assertions = None
    agent_get_dataset_queries = None
    agent_get_entities = None
    agent_get_lineage = None
    agent_list_schema_fields = None
    agent_save_document = None


class ContextUnavailableError(RuntimeError):
    """Raised when the requested live DataHub context cannot be read."""


DEMO_DOWNSTREAM = [
    ImpactNode(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,customer_ltv,PROD)",
        name="customer_ltv",
        type="dataset",
        depth=1,
        owner="Data Platform",
        domain="Commerce",
        platform="dbt",
    ),
    ImpactNode(
        urn="urn:li:dashboard:(looker,revenue_overview)",
        name="Revenue Overview",
        type="dashboard",
        depth=2,
        owner="Revenue Analytics",
        domain="Finance",
        platform="looker",
    ),
    ImpactNode(
        urn="urn:li:mlFeature:(churn_features,customer_id)",
        name="churn_features.customer_id",
        type="ml_feature",
        depth=2,
        owner="ML Platform",
        domain="Growth",
        platform="feature-store",
    ),
]


class DataHubAdapter:
    """DataHub SDK + Agent Context Kit adapter with explicit mode semantics.

    Live mode never substitutes a fixture for an unavailable or incomplete read.
    Demo mode is an intentional, deterministic fixture selected by configuration.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("DATAHUB_GMS_URL", "").rstrip("/")
        self.token = os.getenv("DATAHUB_TOKEN") or os.getenv("DATAHUB_GMS_TOKEN")
        requested_mode = os.getenv("IGRAPH_CONTEXT_MODE", "").strip().lower()
        self.mode = requested_mode or ("live" if self.base_url else "demo")
        if self.mode not in {"live", "demo"}:
            raise ValueError("IGRAPH_CONTEXT_MODE must be either 'live' or 'demo'")
        self.emit_writeback = os.getenv("IGRAPH_ENABLE_WRITEBACK", "false").lower() == "true"
        self.agent_context_enabled = AgentDataHubContext is not None

    @property
    def configured(self) -> bool:
        return self.mode == "live" and bool(self.base_url)

    @property
    def live_requested(self) -> bool:
        return self.mode == "live"

    def _client(self) -> DataHubClient:
        if not self.base_url or Urn is None:
            raise ContextUnavailableError(
                "Live DataHub mode requires DATAHUB_GMS_URL and the DataHub SDK; no demo fallback is permitted"
            )
        return DataHubClient(server=self.base_url, token=self.token)

    async def get_context(self, entity: str, field: str | None = None) -> DataHubContext:
        if self.mode == "demo":
            return self._demo_context(entity)
        try:
            context = await self._live_context(entity, field)
            if context is None or not context.live:
                raise ContextUnavailableError("DataHub returned no complete live context")
            return context
        except ContextUnavailableError:
            raise
        except Exception as exc:
            raise ContextUnavailableError(
                f"Live DataHub context unavailable for {entity!r}: {exc}"
            ) from exc

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("name", "displayName", "display_name", "urn", "username", "owner", "tag", "term", "fieldPath", "field_path"):
                candidate = value.get(key)
                if candidate:
                    return DataHubAdapter._text(candidate)
            return None
        for attr in ("name", "display_name", "displayName", "urn", "value"):
            candidate = getattr(value, attr, None)
            if candidate:
                return str(candidate)
        return str(value)

    @staticmethod
    def _clean_name(value: Any, fallback: str) -> str:
        return DataHubAdapter._text(value) or fallback

    @staticmethod
    def _unwrap_list(value: Any, *keys: str) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        for key in keys:
            nested = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
            if nested is not None:
                return DataHubAdapter._unwrap_list(nested)
        return []

    def _kit_context(self, client: DataHubClient):
        if AgentDataHubContext is None:
            return _NullContext()
        return AgentDataHubContext(client)

    async def _live_context(self, entity: str, field: str | None) -> DataHubContext:
        client = self._client()
        with self._kit_context(client):
            dataset_urn: Urn | None
            if entity.startswith("urn:li:dataset:"):
                parsed = Urn.from_string(entity)
                dataset_urn = parsed if parsed.entity_type == "dataset" else None
            else:
                urns = list(client.search.get_urns(query=entity))
                dataset_urn = next((urn for urn in urns if urn.entity_type == "dataset"), None)
            if dataset_urn is None:
                raise ContextUnavailableError(f"No dataset matched {entity!r}")

            dataset = client.entities.get(dataset_urn)
            if dataset is None:
                raise ContextUnavailableError(f"Dataset {dataset_urn} could not be retrieved")

            lineage_results = list(
                client.lineage.get_lineage(
                    source_urn=dataset_urn,
                    source_column=field,
                    direction="downstream",
                    max_hops=3,
                    count=500,
                )
            )
            downstream = [
                ImpactNode(
                    urn=str(result.urn),
                    name=result.name or str(result.urn),
                    type=str(getattr(result, "type", "unknown")).lower(),
                    depth=int(getattr(result, "hops", 0) or 0),
                )
                for result in lineage_results
            ]

            retrieval_warnings: list[str] = []
            truncated = len(lineage_results) >= 500

            if agent_get_lineage:
                try:
                    kit_lineage = agent_get_lineage(
                        str(dataset_urn),
                        column=field,
                        upstream=False,
                        max_hops=3,
                        max_results=500,
                    )
                    kit_downstream = kit_lineage.get("downstreams") or {}
                    truncated = truncated or bool(kit_downstream.get("hasMore"))
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(f"Agent Context Kit lineage warning: {exc}")

            if agent_get_entities and downstream:
                try:
                    details = agent_get_entities([node.urn for node in downstream])
                    by_urn = {str(item.get("urn")): item for item in details if item.get("urn")}
                    for node in downstream:
                        detail = by_urn.get(node.urn, {})
                        node.owner = self._first_text(detail.get("owners"), "owners")
                        node.domain = self._first_text(detail.get("domain"), "domain")
                        node.platform = self._first_text(detail.get("platform"), "platform")
                        node.description = detail.get("description")
                        node.tags = self._names(detail.get("tags"), "tags", "tag")
                        node.glossary_terms = self._names(
                            detail.get("glossaryTerms"), "terms", "term"
                        )
                        node.column_paths = self._names(
                            detail.get("schemaMetadata"), "fields", "fieldPath"
                        )
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(
                        f"Agent Context Kit downstream enrichment warning: {exc}"
                    )

            owners = [
                self._text(owner.owner) or str(owner.owner)
                for owner in (getattr(dataset, "owners", None) or [])
            ]
            domain = getattr(dataset, "domain", None)
            domains = [self._text(domain)] if domain else []
            tags = [
                str(tag.tag).split(":")[-1]
                for tag in (getattr(dataset, "tags", None) or [])
            ]
            glossary_terms = [
                self._text(term) or str(term)
                for term in (getattr(dataset, "glossary_terms", None) or [])
            ]
            structured_properties = self._structured_properties(
                getattr(dataset, "structured_properties", None)
            )

            schema_fields: list[str] = []
            schema = getattr(dataset, "schema", None)
            if schema:
                try:
                    schema_fields = [str(column.field_path) for column in schema]
                except TypeError:
                    schema_fields = []

            if agent_list_schema_fields:
                try:
                    schema_result = agent_list_schema_fields(str(dataset_urn), limit=500)
                    kit_fields = schema_result.get("fields", [])
                    schema_fields = [
                        str(item.get("fieldPath") or item.get("field_path"))
                        for item in kit_fields
                        if item.get("fieldPath") or item.get("field_path")
                    ] or schema_fields
                    truncated = truncated or bool(
                        schema_result.get("remainingCount", 0) > 0
                    )
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(
                        f"Agent Context Kit schema warning: {exc}"
                    )

            assertions: list[str] = []
            assertion_statuses: dict[str, str] = {}
            agent_assertions_retrieved = False

            if agent_get_dataset_assertions:
                try:
                    assertion_result = agent_get_dataset_assertions(
                        str(dataset_urn),
                        count=20,
                    )
                    entries = (assertion_result.get("data") or {}).get(
                        "assertions",
                        [],
                    )
                    agent_assertions_retrieved = (
                        assertion_result.get("success", True) is not False
                    )
                    for item in entries:
                        assertion_urn = str(item.get("urn"))
                        assertions.append(assertion_urn)
                        summary = item.get("runSummary") or {}
                        assertion_statuses[assertion_urn] = (
                            "failing" if summary.get("failed", 0) else "passing"
                        )
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(
                        f"Agent Context Kit assertions warning: {exc}"
                    )

            if not assertions and not agent_assertions_retrieved:
                try:
                    for assertion in client.assertions.get_assertions_for_entity(
                        dataset_urn
                    ):
                        assertions.append(str(getattr(assertion, "urn", assertion)))
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(
                        f"DataHub assertion read warning: {exc}"
                    )

            query_count: int | None = None
            query_usage: list[str] = []

            if agent_get_dataset_queries:
                try:
                    query_result = agent_get_dataset_queries(
                        str(dataset_urn),
                        column=field,
                        count=20,
                    )
                    query_count = int(query_result.get("total", 0))
                    for query in query_result.get("queries", []):
                        statement = (
                            (query.get("properties") or {})
                            .get("statement", {})
                            .get("value")
                        )
                        if statement:
                            query_usage.append(str(statement)[:500])
                except Exception as exc:  # noqa: BLE001
                    retrieval_warnings.append(
                        f"Agent Context Kit query-history warning: {exc}"
                    )

            source_name = getattr(dataset, "display_name", None) or getattr(
                dataset_urn,
                "name",
                None,
            )

            return DataHubContext(
                source_urn=str(dataset_urn),
                source_name=source_name or str(dataset_urn),
                schema_fields=schema_fields,
                owners=owners,
                domains=[domain for domain in domains if domain],
                tags=tags,
                glossary_terms=glossary_terms,
                structured_properties=structured_properties,
                downstream=downstream,
                assertions=assertions,
                assertion_statuses=assertion_statuses,
                query_count=query_count,
                query_usage=query_usage,
                description=getattr(dataset, "description", None),
                live=True,
                retrieval_complete=not truncated and not retrieval_warnings,
                truncated=truncated,
                retrieval_warnings=retrieval_warnings,
            )

    @classmethod
    def _first_text(cls, value: Any, *keys: str) -> str | None:
        values = cls._unwrap_list(value, *keys)
        if not values and value:
            values = [value]
        for item in values:
            text = cls._text(item)
            if text:
                return text
        return None

    @classmethod
    def _structured_properties(cls, value: Any) -> dict[str, str]:
        """Normalize SDK structured-property assignments for the API model."""
        if not value:
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}

        entries = cls._unwrap_list(value, "properties")
        if not entries:
            entries = [value]

        result: dict[str, str] = {}
        for entry in entries:
            if isinstance(entry, dict):
                key = (
                    entry.get("propertyUrn")
                    or entry.get("property_urn")
                    or entry.get("name")
                    or entry.get("urn")
                )
                raw_values = entry.get("values")
                if raw_values is None:
                    raw_values = entry.get("value")
            else:
                key = (
                    getattr(entry, "propertyUrn", None)
                    or getattr(entry, "property_urn", None)
                    or getattr(entry, "name", None)
                    or getattr(entry, "urn", None)
                )
                raw_values = getattr(entry, "values", None)
                if raw_values is None:
                    raw_values = getattr(entry, "value", None)

            if key is None:
                continue
            if isinstance(raw_values, (list, tuple, set)):
                rendered = ", ".join(str(item) for item in raw_values)
            else:
                rendered = "" if raw_values is None else str(raw_values)
            result[str(key)] = rendered

        return result

    @classmethod
    def _names(cls, value: Any, *keys: str) -> list[str]:
        result: list[str] = []
        for item in cls._unwrap_list(value, *keys):
            text = cls._text(item)
            if text:
                result.append(text.split(":")[-1])
        return sorted(set(result))

    def _demo_context(self, entity: str) -> DataHubContext:
        source_name = (
            entity.rsplit(",", 2)[-2]
            if entity.startswith("urn:li:dataset:")
            else entity
        )

        return DataHubContext(
            source_urn=(
                entity
                if entity.startswith("urn:li:dataset:")
                else f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{entity},PROD)"
            ),
            source_name=source_name,
            schema_fields=["order_id", "customer_id", "created_at", "amount"],
            owners=["Data Platform"],
            domains=["Commerce"],
            tags=["production", "customer-data"],
            glossary_terms=["Customer Identifier"],
            structured_properties={"lifecycle": "production"},
            downstream=[node.model_copy(deep=True) for node in DEMO_DOWNSTREAM],
            assertions=["schema_compatibility", "freshness_sla"],
            assertion_statuses={
                "schema_compatibility": "passing",
                "freshness_sla": "passing",
            },
            query_count=12,
            query_usage=[
                "SELECT customer_id, amount FROM orders WHERE created_at >= ?"
            ],
            documents=["urn:li:document:igraph-demo-context"],
            description=(
                "Deterministic context shaped after the "
                "DataHub showcase-ecommerce graph."
            ),
            live=False,
        )

    async def writeback(
        self,
        urn: str,
        pact_id: str,
        risk: str,
        status: str,
        context_hash: str,
        receipt_markdown: str | None = None,
    ) -> DataHubWriteback:
        properties = {
            "igraph.pact_id": pact_id,
            "igraph.risk": risk,
            "igraph.status": status,
            "igraph.context_hash": context_hash,
        }

        if self.mode == "demo":
            return DataHubWriteback(
                target_urn=urn,
                mode="demo",
                properties=properties,
            )

        if not self.emit_writeback:
            return DataHubWriteback(
                target_urn=urn,
                mode="skipped",
                properties=properties,
            )

        document_urn: str | None = None
        document_status: str | None = None

        try:
            client = self._client()

            with self._kit_context(client):
                entity = client.entities.get(Urn.from_string(urn))
                if entity is None:
                    raise ContextUnavailableError(
                        f"Cannot write back: entity {urn} was not found"
                    )

                current = dict(getattr(entity, "custom_properties", {}) or {})
                current.update(properties)
                entity.set_custom_properties(current)
                client.entities.update(entity)

                if agent_save_document and receipt_markdown:
                    document_result = agent_save_document(
                        document_type="Decision",
                        title=f"iGraph Change Receipt {pact_id}",
                        content=receipt_markdown,
                        topics=["igraph", "change-control", risk],
                        related_assets=[urn],
                    )
                    document_urn = document_result.get("urn")
                    document_status = (
                        "saved"
                        if document_result.get("success")
                        else "failed"
                    )
                else:
                    document_status = "skipped"

            return DataHubWriteback(
                target_urn=urn,
                mode="emitted",
                properties=properties,
                document_urn=document_urn,
                document_status=document_status,
            )

        except Exception as exc:  # noqa: BLE001
            return DataHubWriteback(
                target_urn=urn,
                mode="failed",
                properties=properties,
                document_urn=document_urn,
                document_status=document_status,
                error=str(exc),
                           )

    async def discover_candidates(self, query: str = "*") -> list[DataHubContext]:
        if self.mode == "demo":
            return [self._demo_context("orders")]

        client = self._client()
        contexts: list[DataHubContext] = []

        if not query or query == "*":
            if SearchFilter is None:
                raise ContextUnavailableError(
                    "Live wildcard discovery requires DataHub SDK FilterDsl"
                )
            urns = client.search.get_urns(
                filter=SearchFilter.entity_type("dataset")
            )
        else:
            urns = client.search.get_urns(query=query)

        for urn in list(urns)[:30]:
            if urn.entity_type != "dataset":
                continue
            contexts.append(await self.get_context(str(urn)))

        return contexts


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None
