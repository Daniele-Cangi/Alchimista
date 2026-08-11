from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException, Request

from services.privacy_service.engine import PrivacyEngine, build_detector
from services.privacy_service.vault import PiiVaultRepository, VaultCipher
from services.shared.config import load_runtime_config
from services.shared.db import get_connection
from services.shared.privacy import (
    PrivacyDetectRequest,
    PrivacyDetectResponse,
    PrivacyPseudonymizeRequest,
    PrivacyPseudonymizeResponse,
    PrivacyRestoreRequest,
    PrivacyRestoreResponse,
)


config = load_runtime_config()
if not config.privacy_vault_key:
    raise RuntimeError("PRIVACY_VAULT_KEY is required by privacy-service")

cipher = VaultCipher.from_base64(config.privacy_vault_key, config.privacy_vault_key_version)
vault = PiiVaultRepository(config.database_url, cipher)
detector = build_detector(
    config.privacy_detector,
    rizzo_url=os.getenv("RIZZO_BASE_URL", ""),
    timeout_seconds=config.privacy_timeout_seconds,
)
engine = PrivacyEngine(detector=detector, cipher=cipher, vault=vault)
app = FastAPI(title="alchimista-privacy-service", version="0.1.0")


@app.get("/v1/privacy/health")
def health() -> dict:
    return {"status": "ok", "engine": detector.metadata.model_dump(mode="json")}


@app.get("/v1/privacy/ready")
def ready() -> dict:
    try:
        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        if not detector.ready():
            raise RuntimeError("Privacy detector is not ready")
        return {"status": "ready", "engine": detector.metadata.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Privacy vault database is not ready") from exc


@app.post("/v1/privacy/detect", response_model=PrivacyDetectResponse)
def detect(payload: PrivacyDetectRequest, request: Request) -> PrivacyDetectResponse:
    _require_service_token(request)
    result = engine.protect(
        text=payload.text,
        tenant=payload.tenant,
        doc_id=payload.doc_id,
        replace=False,
        reversible=False,
        persist_mapping=False,
    )
    return PrivacyDetectResponse(
        findings=result.findings,
        pii_count=len(result.findings),
        pii_types=sorted({finding.type for finding in result.findings}),
        engine=detector.metadata,
    )


@app.post("/v1/privacy/pseudonymize", response_model=PrivacyPseudonymizeResponse)
def pseudonymize(payload: PrivacyPseudonymizeRequest, request: Request) -> PrivacyPseudonymizeResponse:
    _require_service_token(request)
    if payload.reversible and not config.privacy_mapping_enabled:
        raise HTTPException(status_code=409, detail="Reversible mappings are disabled")
    try:
        result = engine.protect(
            text=payload.text,
            tenant=payload.tenant,
            doc_id=payload.doc_id,
            replace=True,
            reversible=payload.reversible,
            persist_mapping=payload.persist_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PrivacyPseudonymizeResponse(
        protected_text=result.protected_text,
        findings=result.findings,
        pii_count=len(result.findings),
        pii_types=sorted({finding.type for finding in result.findings}),
        engine=detector.metadata,
        reversible=payload.reversible,
        mapping_stored=payload.reversible and payload.persist_mapping and bool(result.findings),
    )


@app.post("/v1/privacy/restore", response_model=PrivacyRestoreResponse)
def restore(payload: PrivacyRestoreRequest, request: Request) -> PrivacyRestoreResponse:
    _require_service_token(request)
    if not config.privacy_mapping_enabled:
        raise HTTPException(status_code=409, detail="Reversible mappings are disabled")
    try:
        restored_text, restored_count = vault.restore(
            tenant=payload.tenant,
            doc_id=payload.doc_id,
            text=payload.text,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Unable to decrypt privacy mapping") from exc
    return PrivacyRestoreResponse(
        restored_text=restored_text,
        restored_count=restored_count,
        engine=detector.metadata,
    )


def _require_service_token(request: Request) -> None:
    provided = request.headers.get("x-privacy-token", "")
    if not config.privacy_service_token:
        raise HTTPException(status_code=503, detail="Privacy service token is not configured")
    if not hmac.compare_digest(provided, config.privacy_service_token):
        raise HTTPException(status_code=401, detail="Invalid privacy service token")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("services.privacy_service.main:app", host="0.0.0.0", port=port)
