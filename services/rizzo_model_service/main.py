from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.rizzo_model_service.runtime import ModelRuntime, ModelState


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)


runtime = ModelRuntime(os.getenv("RIZZO_MODEL_ROOT", "/models"))
app = FastAPI(title="alchimista-rizzo-model-service", version="0.1.0")


@app.get("/health")
def health() -> dict:
    current = runtime.status()
    if current["state"] != ModelState.READY.value:
        raise HTTPException(status_code=503, detail="Rizzo model is not loaded")
    return {"status": "ready", **current}


@app.get("/v1/model/status")
def model_status(request: Request) -> dict:
    _require_token(request)
    return runtime.status()


@app.post("/v1/model/install", status_code=status.HTTP_202_ACCEPTED)
def install(request: Request) -> dict:
    _require_token(request)
    return runtime.install_async()


@app.post("/v1/model/load", status_code=status.HTTP_202_ACCEPTED)
def load(request: Request) -> dict:
    _require_token(request)
    try:
        return runtime.load_async()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/model/unload")
def unload(request: Request) -> dict:
    _require_token(request)
    try:
        return runtime.unload()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/analyze")
def analyze(payload: AnalyzeRequest, request: Request) -> dict:
    _require_token(request)
    try:
        return runtime.analyze(payload.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_token(request: Request) -> None:
    configured = os.getenv("RIZZO_MODEL_TOKEN", "")
    provided = request.headers.get("x-model-token", "")
    if len(configured) < 24:
        raise HTTPException(status_code=503, detail="Rizzo model token is not configured")
    if not hmac.compare_digest(provided, configured):
        raise HTTPException(status_code=401, detail="Invalid Rizzo model token")
