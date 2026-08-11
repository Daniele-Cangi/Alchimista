from __future__ import annotations

import hmac
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Request, status

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
    PrivacySettings,
    PrivacySettingsUpdate,
)
from services.shared.runtime_settings import PrivacyRuntimeSettings, RuntimeSettingsStore


config = load_runtime_config()
cipher = VaultCipher.from_configuration(
    active_key_version=config.privacy_vault_active_key_version,
    keys_json=config.privacy_vault_keys_json,
    legacy_key=config.privacy_vault_key,
    legacy_key_version=config.privacy_vault_key_version,
)
vault = PiiVaultRepository(config.database_url, cipher)
settings_store = RuntimeSettingsStore(
    config.database_url,
    default_policy=config.privacy_policy,
    default_detector=config.privacy_detector,
    default_mapping_enabled=config.privacy_mapping_enabled,
)
rizzo_url = os.getenv("RIZZO_BASE_URL", "").rstrip("/")
rizzo_token = os.getenv("RIZZO_MODEL_TOKEN", "")
detectors = {
    "rizzo_regex": build_detector("rizzo_regex"),
}
if rizzo_url:
    detectors["rizzo_http"] = build_detector(
        "rizzo_http",
        rizzo_url=rizzo_url,
        timeout_seconds=config.privacy_timeout_seconds,
        rizzo_token=rizzo_token,
    )
app = FastAPI(title="alchimista-privacy-service", version="0.2.0")


@app.get("/v1/privacy/health")
def health() -> dict[str, Any]:
    selected = settings_store.get(config.default_tenant)
    detector = detectors.get(selected.privacy_detector)
    return {
        "status": "ok",
        "workspace": selected.workspace,
        "privacy_policy": selected.privacy_policy,
        "privacy_detector": selected.privacy_detector,
        "detector_ready": bool(detector and detector.ready()),
    }


@app.get("/v1/privacy/ready")
def ready() -> dict[str, Any]:
    try:
        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        selected = settings_store.get(config.default_tenant)
        detector = detectors.get(selected.privacy_detector)
        detector_ready = bool(detector and detector.ready())
        if vault.unavailable_key_versions():
            raise RuntimeError("Privacy vault contains unavailable key versions")
        return {
            "status": "ready",
            "workspace": selected.workspace,
            "privacy_policy": selected.privacy_policy,
            "privacy_detector": selected.privacy_detector,
            "detector_ready": detector_ready,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Privacy service is not ready") from exc


@app.get("/v1/privacy/settings", response_model=PrivacySettings)
def get_settings(request: Request, workspace: str = "default") -> PrivacySettings:
    _require_service_token(request)
    return _settings_response(settings_store.get(workspace))


@app.put("/v1/privacy/settings", response_model=PrivacySettings)
def update_settings(payload: PrivacySettingsUpdate, request: Request) -> PrivacySettings:
    _require_service_token(request)
    if payload.privacy_detector.value == "rizzo_http":
        detector = detectors.get("rizzo_http")
        if detector is None or not detector.ready():
            raise HTTPException(
                status_code=409,
                detail="Install and load the full Rizzo model before activating it",
            )
    selected = settings_store.update(
        workspace=payload.workspace,
        privacy_policy=payload.privacy_policy.value,
        privacy_detector=payload.privacy_detector.value,
        privacy_mapping_enabled=payload.privacy_mapping_enabled,
    )
    return _settings_response(selected)


@app.get("/v1/privacy/model")
def model_status(request: Request) -> dict[str, Any]:
    _require_service_token(request)
    return _model_request("GET", "/v1/model/status")


@app.post("/v1/privacy/model/{action}", status_code=status.HTTP_202_ACCEPTED)
def model_action(action: str, request: Request) -> dict[str, Any]:
    _require_service_token(request)
    if action not in {"install", "load", "unload"}:
        raise HTTPException(status_code=404, detail="Unknown model action")
    if action == "unload":
        active_workspaces = settings_store.workspaces_using_detector("rizzo_http")
        if active_workspaces:
            raise HTTPException(
                status_code=409,
                detail="Switch every workspace to Rizzo Lightweight before unloading the full model",
            )
    return _model_request("POST", f"/v1/model/{quote(action)}")


@app.post("/v1/privacy/detect", response_model=PrivacyDetectResponse)
def detect(payload: PrivacyDetectRequest, request: Request) -> PrivacyDetectResponse:
    _require_service_token(request)
    engine, selected = _engine_for(payload.tenant)
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
        engine=engine.detector.metadata,
    )


@app.post("/v1/privacy/pseudonymize", response_model=PrivacyPseudonymizeResponse)
def pseudonymize(payload: PrivacyPseudonymizeRequest, request: Request) -> PrivacyPseudonymizeResponse:
    _require_service_token(request)
    engine, selected = _engine_for(payload.tenant)
    if payload.reversible and not selected.privacy_mapping_enabled:
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
        engine=engine.detector.metadata,
        reversible=payload.reversible,
        mapping_stored=payload.reversible and payload.persist_mapping and bool(result.findings),
    )


@app.post("/v1/privacy/restore", response_model=PrivacyRestoreResponse)
def restore(payload: PrivacyRestoreRequest, request: Request) -> PrivacyRestoreResponse:
    _require_service_token(request)
    engine, selected = _engine_for(payload.tenant)
    if not selected.privacy_mapping_enabled:
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
        engine=engine.detector.metadata,
    )


def _engine_for(workspace: str) -> tuple[PrivacyEngine, PrivacyRuntimeSettings]:
    selected = settings_store.get(workspace)
    detector = detectors.get(selected.privacy_detector)
    if detector is None:
        raise HTTPException(status_code=503, detail="Selected privacy detector is not configured")
    if selected.privacy_policy != "off" and not detector.ready():
        raise HTTPException(status_code=503, detail="Selected privacy detector is not ready")
    return PrivacyEngine(detector=detector, cipher=cipher, vault=vault), selected


def _settings_response(selected: PrivacyRuntimeSettings) -> PrivacySettings:
    model: dict[str, Any] | None
    try:
        model = _model_request("GET", "/v1/model/status") if rizzo_url and rizzo_token else None
    except HTTPException:
        model = {"state": "UNAVAILABLE", "loaded": False, "installed": False}
    return PrivacySettings(
        **selected.as_dict(),
        vault_key_version=cipher.key_version,
        model=model,
    )


def _model_request(method: str, path: str) -> dict[str, Any]:
    if not rizzo_url or not rizzo_token:
        raise HTTPException(status_code=503, detail="Rizzo model service is not configured")
    request = UrlRequest(
        rizzo_url + path,
        data=b"" if method == "POST" else None,
        headers={"x-model-token": rizzo_token, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=max(10, config.privacy_timeout_seconds)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = "Rizzo model action was rejected"
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
            detail = str(parsed.get("detail") or detail)
        except Exception:
            pass
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Rizzo model service is unavailable") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Rizzo model service returned an invalid response")
    return body


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
