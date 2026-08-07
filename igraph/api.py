from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from igraph.datahub_adapter import DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.models import (
    AnalysisResponse,
    AuthorityDriftExperiment,
    ChangeRequest,
    DiscoveryResponse,
    ExecuteActionRequest,
    ExecuteActionResponse,
    ImpactPact,
    VerificationResponse,
)

app = FastAPI(
    title="iGraph",
    description="Context-derived execution control for autonomous data changes using DataHub.",
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ImpactEngine(DataHubAdapter())


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "igraph",
        "datahub_configured": engine.datahub.configured,
        "writeback_enabled": engine.datahub.emit_writeback,
    }


@app.post("/v1/analyze", response_model=AnalysisResponse)
async def analyze_change(request: ChangeRequest) -> AnalysisResponse:
    return await engine.analyze(request)


@app.post("/v1/actions/execute", response_model=ExecuteActionResponse)
async def execute_guarded_action(request: ExecuteActionRequest) -> ExecuteActionResponse:
    return await engine.execute_action(
        pact=request.pact,
        action=request.action,
        parameters=request.parameters,
        human_approved=request.human_approved,
    )


@app.post("/v1/verify", response_model=VerificationResponse)
async def verify_change(pact: ImpactPact) -> VerificationResponse:
    return await engine.verify(pact)


@app.get("/v1/discover", response_model=DiscoveryResponse)
async def discover_golden_demo(query: str = "*") -> DiscoveryResponse:
    return await engine.discover(query)


@app.get("/v1/experiments/authority-drift", response_model=AuthorityDriftExperiment)
def authority_drift_experiment() -> AuthorityDriftExperiment:
    return engine.authority_drift_experiment()
