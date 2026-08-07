from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from igraph.datahub_adapter import DataHubAdapter
from igraph.engine import ImpactEngine
from igraph.models import AnalysisResponse, ChangeRequest

app = FastAPI(
    title="iGraph",
    description="Context-aware change control for autonomous data agents using DataHub.",
    version="0.1.0",
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
def health() -> dict[str, str]:
    return {"status": "ok", "service": "igraph"}


@app.post("/v1/analyze", response_model=AnalysisResponse)
async def analyze_change(request: ChangeRequest) -> AnalysisResponse:
    return await engine.analyze(request)
