from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeRequest(BaseModel):
    action: Literal["rename_column", "drop_column", "change_type", "modify_asset"]
    entity: str
    field: str | None = None
    replacement: str | None = None
    requested_action: str | None = None


class ImpactNode(BaseModel):
    urn: str
    name: str
    type: str
    depth: int = 0
    owner: str | None = None
    domain: str | None = None
    tags: list[str] = Field(default_factory=list)


class DataHubContext(BaseModel):
    source_urn: str
    source_name: str
    owners: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    downstream: list[ImpactNode] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    description: str | None = None
    live: bool = False


class RiskAssessment(BaseModel):
    tier: RiskTier
    score: int = Field(ge=0, le=100)
    reasons: list[str]


class ImpactPact(BaseModel):
    pact_id: str
    request: ChangeRequest
    context: DataHubContext
    risk: RiskAssessment
    allowed_actions: list[str]
    blocked_actions: list[str]
    required_validations: list[str]
    requires_human_approval: list[str]


class GuardDecision(BaseModel):
    action: str
    allowed: bool
    reason: str


class ChangeReceipt(BaseModel):
    receipt_id: str
    pact_id: str
    status: Literal["ready_for_review", "blocked", "failed"]
    attempted_actions: list[GuardDecision]
    generated_artifacts: list[str]
    validations: dict[str, bool]
    writeback: dict[str, str]


class AnalysisResponse(BaseModel):
    pact: ImpactPact
    receipt: ChangeReceipt
