from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from igraph.datahub_adapter import DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.models import (
    AnalysisResponse,
    ChangeRequest,
    DiscoveryResponse,
    ImpactPact,
    VerificationResponse,
)

app = FastAPI(
    title="iGraph",
    description="Context-aware change control for autonomous data agents using DataHub.",
    version="0.2.0",
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


@app.post("/v1/verify", response_model=VerificationResponse)
async def verify_change(pact: ImpactPact) -> VerificationResponse:
    return await engine.verify(pact)


@app.get("/v1/discover", response_model=DiscoveryResponse)
async def discover_golden_demo(query: str = "*") -> DiscoveryResponse:
    return await engine.discover(query)
