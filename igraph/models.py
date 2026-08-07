from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    PENDING = "pending"
    FAIL = "fail"


class ExecutionStatus(StrEnum):
    DENIED = "denied"
    EXECUTED = "executed"
    PREPARED = "prepared"
    FAILED = "failed"


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
    schema_fields: list[str] = Field(default_factory=list)
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
    context_hash: str
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


class GeneratedArtifact(BaseModel):
    path: str
    kind: str
    sha256: str
    content: str


class ValidationResult(BaseModel):
    name: str
    status: ValidationStatus
    evidence: str


class ExecutionEvent(BaseModel):
    action: str
    status: ExecutionStatus
    executor_invoked: bool
    decision: GuardDecision
    evidence_sha256: str | None = None
    detail: str


class DataHubWriteback(BaseModel):
    target_urn: str
    mode: Literal["emitted", "skipped", "demo", "failed"]
    properties: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class ChangeReceipt(BaseModel):
    receipt_id: str
    pact_id: str
    status: Literal["ready_for_review", "blocked", "failed"]
    attempted_actions: list[GuardDecision]
    execution_events: list[ExecutionEvent] = Field(default_factory=list)
    generated_artifacts: list[GeneratedArtifact]
    validations: list[ValidationResult]
    writeback: DataHubWriteback


class AnalysisResponse(BaseModel):
    pact: ImpactPact
    receipt: ChangeReceipt


class ExecuteActionRequest(BaseModel):
    pact: ImpactPact
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    human_approved: bool = False


class ExecuteActionResponse(BaseModel):
    pact_id: str
    decision: GuardDecision
    event: ExecutionEvent
    receipt: ChangeReceipt


class VerificationResponse(BaseModel):
    pact_id: str
    pre_context_hash: str
    post_context_hash: str
    validations: list[ValidationResult]
    verified: bool


class DiscoveryCandidate(BaseModel):
    urn: str
    name: str
    downstream_count: int
    dashboard_count: int
    ml_count: int
    risk_score: int


class DiscoveryResponse(BaseModel):
    live: bool
    candidates: list[DiscoveryCandidate]


class AuthorityDelta(BaseModel):
    newly_allowed: list[str] = Field(default_factory=list)
    newly_blocked: list[str] = Field(default_factory=list)
    newly_requires_approval: list[str] = Field(default_factory=list)


class AuthorityDriftExperiment(BaseModel):
    request: ChangeRequest
    before: ImpactPact
    after: ImpactPact
    tested_action: str
    before_decision: GuardDecision
    after_decision: GuardDecision
    delta: AuthorityDelta
    claim: str
