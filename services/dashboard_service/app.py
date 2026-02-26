"""Alchimista Dashboard service: web UI + compatibility proxy."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

INGEST_URL = os.getenv("INGEST_URL", "http://localhost:8011")
PROCESSOR_URL = os.getenv("PROCESSOR_URL", "http://localhost:8012")
RAG_URL = os.getenv("RAG_URL", "http://localhost:8013")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

# Optional demo convenience mode. Keep disabled in hardened environments.
DASHBOARD_ENABLE_TEST_TOKEN = os.getenv("DASHBOARD_ENABLE_TEST_TOKEN", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DASHBOARD_DEPLOY_ENV = (
    os.getenv("DASHBOARD_DEPLOY_ENV")
    or os.getenv("VERCEL_ENV")
    or os.getenv("ENVIRONMENT")
    or "unknown"
).strip().lower()
DASHBOARD_ALLOW_TEST_TOKEN_IN_PROD = os.getenv("DASHBOARD_ALLOW_TEST_TOKEN_IN_PROD", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_DASHBOARD_TEST_TOKEN_PROD_BLOCKED = (
    DASHBOARD_ENABLE_TEST_TOKEN
    and DASHBOARD_DEPLOY_ENV == "production"
    and not DASHBOARD_ALLOW_TEST_TOKEN_IN_PROD
)
DASHBOARD_TEST_TOKEN_ENABLED = DASHBOARD_ENABLE_TEST_TOKEN and not _DASHBOARD_TEST_TOKEN_PROD_BLOCKED
AUTH0_TEST_DOMAIN = os.getenv("AUTH0_TEST_DOMAIN", "alchimista.eu.auth0.com").strip()
AUTH0_TEST_AUDIENCE = os.getenv("AUTH0_TEST_AUDIENCE", "https://api.alchimista.ai").strip()
AUTH0_TEST_CLIENT_ID = os.getenv("AUTH0_TEST_CLIENT_ID", "").strip()
AUTH0_TEST_CLIENT_SECRET = os.getenv("AUTH0_TEST_CLIENT_SECRET", "").strip()
_TEST_TOKEN_CACHE: dict[str, Any] = {"access_token": "", "token_type": "Bearer", "expires_in": 0, "expires_at": 0.0}


# ==================== APP SETUP ====================

app = FastAPI(
    title="Alchimista Dashboard",
    description="Management UI and compatibility proxy for Alchimista services",
    version="2.1.0",
)

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")


@app.on_event("startup")
async def startup_security_checks() -> None:
    if _DASHBOARD_TEST_TOKEN_PROD_BLOCKED:
        logger.warning(
            "Security check: DASHBOARD_ENABLE_TEST_TOKEN=true but endpoint is HARD-DISABLED in production "
            "(set DASHBOARD_ALLOW_TEST_TOKEN_IN_PROD=true only for controlled demos)."
        )
    if DASHBOARD_TEST_TOKEN_ENABLED:
        logger.warning(
            "Security check: test token endpoint is ENABLED in env=%s. Intended for test/demo only.",
            DASHBOARD_DEPLOY_ENV,
        )


# ==================== PROXY HELPERS ====================

def _headers(auth: str | None = None, admin_key: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if auth:
        headers["Authorization"] = auth
    if admin_key:
        headers["x-admin-key"] = admin_key
    return headers


def _decode_json(resp: requests.Response) -> dict[str, Any]:
    if not resp.content:
        return {}
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"items": data}
    except ValueError:
        return {"raw": resp.text}


async def _proxy_get(
    url: str,
    params: dict[str, Any] | None = None,
    auth: str | None = None,
    admin_key: str | None = None,
) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    resp = requests.get(url, params=clean_params, headers=_headers(auth, admin_key), timeout=30)
    resp.raise_for_status()
    return _decode_json(resp)


async def _proxy_post(
    url: str,
    body: dict[str, Any] | None = None,
    auth: str | None = None,
    admin_key: str | None = None,
) -> dict[str, Any]:
    resp = requests.post(url, json=body or {}, headers=_headers(auth, admin_key), timeout=60)
    resp.raise_for_status()
    return _decode_json(resp)


def _http_err(exc: requests.HTTPError) -> HTTPException:
    response = exc.response
    status_code = response.status_code if response is not None else 502
    detail = str(exc)
    try:
        detail_json = response.json() if response is not None else {"detail": str(exc)}
        detail = detail_json.get("detail", detail_json)
    except ValueError:
        pass
    return HTTPException(status_code=status_code, detail=detail)


def _gw_err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def _effective_admin_key(x_admin_key: str | None) -> str | None:
    if x_admin_key:
        return x_admin_key
    if ADMIN_KEY:
        return ADMIN_KEY
    return None


def _mint_auth0_test_token() -> dict[str, Any]:
    if not DASHBOARD_TEST_TOKEN_ENABLED:
        raise HTTPException(
            status_code=403,
            detail=(
                "Test token endpoint is disabled. "
                "In production it requires DASHBOARD_ALLOW_TEST_TOKEN_IN_PROD=true in addition to DASHBOARD_ENABLE_TEST_TOKEN=true."
            ),
        )
    if not AUTH0_TEST_CLIENT_ID or not AUTH0_TEST_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="AUTH0_TEST_CLIENT_ID/AUTH0_TEST_CLIENT_SECRET are not configured.",
        )
    if not AUTH0_TEST_DOMAIN or not AUTH0_TEST_AUDIENCE:
        raise HTTPException(
            status_code=503,
            detail="AUTH0_TEST_DOMAIN/AUTH0_TEST_AUDIENCE are not configured.",
        )

    now = time.time()
    cached_token = str(_TEST_TOKEN_CACHE.get("access_token") or "")
    cached_expiry = float(_TEST_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached_token and cached_expiry > now + 30:
        return {
            "access_token": cached_token,
            "token_type": str(_TEST_TOKEN_CACHE.get("token_type") or "Bearer"),
            "expires_in": max(0, int(cached_expiry - now)),
        }

    token_url = f"https://{AUTH0_TEST_DOMAIN}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": AUTH0_TEST_CLIENT_ID,
        "client_secret": AUTH0_TEST_CLIENT_SECRET,
        "audience": AUTH0_TEST_AUDIENCE,
    }
    try:
        response = requests.post(token_url, json=payload, timeout=15)
        body = _decode_json(response)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to reach Auth0 token endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Auth0 token request failed ({response.status_code}): {body.get('error_description') or body.get('detail') or body}",
        )

    token = str(body.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=502, detail=f"Auth0 token response missing access_token: {body}")

    token_type = str(body.get("token_type") or "Bearer")
    expires_in = int(body.get("expires_in") or 3600)
    _TEST_TOKEN_CACHE.update(
        {
            "access_token": token,
            "token_type": token_type,
            "expires_in": expires_in,
            "expires_at": now + max(1, expires_in),
        }
    )

    return {
        "access_token": token,
        "token_type": token_type,
        "expires_in": expires_in,
    }


def _date_floor(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if len(raw) == 10:
        return f"{raw}T00:00:00+00:00"
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _date_ceil(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if len(raw) == 10:
        return f"{raw}T23:59:59.999999+00:00"
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _first_non_empty(values: list[Any], default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate:
            return candidate
    return default


def _unique_strings(values: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


# ==================== PAGE ROUTES ====================

def _html_page(filename: str) -> FileResponse:
    page = TEMPLATES_DIR / filename
    if not page.exists():
        raise HTTPException(status_code=404, detail=f"Page not found: {filename}")
    return FileResponse(page, media_type="text/html; charset=utf-8")


@app.get("/")
async def landing():
    return _html_page("dux_landing.html")


@app.get("/dashboard")
async def dashboard():
    return _html_page("dux_dashboard.html")


@app.get("/ingest")
async def ingest_page():
    return _html_page("dux_ingest.html")


@app.get("/connectors")
async def connectors_page():
    return _html_page("dux_connectors.html")


@app.get("/query")
async def query_page():
    return _html_page("dux_query.html")


@app.get("/decisions")
async def decisions_page():
    return _html_page("dux_decisions.html")


@app.get("/governance")
async def governance_page():
    return _html_page("dux_governance.html")


@app.get("/monitoring")
async def monitoring_page():
    return _html_page("dux_monitoring.html")


@app.get("/quality")
async def quality_page():
    return _html_page("dux_quality.html")


@app.get("/settings")
async def settings_page():
    return _html_page("dux_settings.html")


@app.get("/guide")
async def guide_page():
    return _html_page("dux_guide.html")


@app.get("/tutorial")
async def tutorial_page():
    return _html_page("dux_tutorial.html")


# ==================== MODELS ====================

class IngestRequest(BaseModel):
    tenant: str = Field(min_length=1)
    source_uri: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size: int | None = Field(default=None, ge=0)
    doc_id: str | None = None
    trace_id: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "IngestRequest":
        if not (self.source_uri or self.filename):
            raise ValueError("source_uri or filename is required")
        return self


class IngestCompleteRequest(BaseModel):
    job_id: str | None = None
    doc_id: str | None = None
    tenant: str = Field(min_length=1)
    trace_id: str | None = None
    gcs_uri: str | None = None
    force_reprocess: bool = False

    @model_validator(mode="after")
    def validate_ids(self) -> "IngestCompleteRequest":
        if not (self.doc_id or self.job_id):
            raise ValueError("doc_id or job_id is required")
        return self


class GCSImportRequest(BaseModel):
    tenant: str = Field(min_length=1)
    source_gcs_uri: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    doc_id: str | None = None
    trace_id: str | None = None
    force_reprocess: bool = False
    publish: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> "GCSImportRequest":
        if not self.source_gcs_uri and not self.bucket:
            raise ValueError("source_gcs_uri or bucket is required")
        return self


class QueryRequest(BaseModel):
    tenant: str = Field(min_length=1)
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)
    doc_ids: list[str] | None = None


class DecisionRequest(BaseModel):
    tenant: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    decision_type: str = Field(default="rag_answer", min_length=1)
    subject_id: str | None = None
    context: dict[str, Any] | None = None
    citations: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class DecisionQueryRequest(BaseModel):
    tenant: str = Field(min_length=1)
    trace_id: str | None = None
    subject_id: str | None = None
    decision_type: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class RetentionPolicyRequest(BaseModel):
    tenant: str = Field(min_length=1)
    policy_name: str | None = None
    retention_days: int = Field(ge=1, le=3650)
    doc_types: list[str] | None = None
    action: str = "delete"
    artifact_type: str | None = None


class LegalHoldRequest(BaseModel):
    tenant: str = Field(min_length=1)
    hold_name: str = Field(min_length=1)
    reason: str = Field(min_length=3)
    doc_ids: list[str] | None = None
    query_filter: dict[str, Any] | None = None


class RetentionEnforceRequest(BaseModel):
    tenant: str | None = None
    dry_run: bool = True
    artifact_type: str | None = "audit_artifacts"
    limit: int | None = Field(default=200, ge=1, le=1000)


# ==================== INGEST ====================

@app.post("/api/v1/ingest")
async def api_ingest(body: IngestRequest, authorization: str | None = Header(default=None)):
    """Compatibility endpoint used by dashboard forms."""
    try:
        if body.source_uri:
            source_uri = body.source_uri.strip()
            if not source_uri.startswith("gs://"):
                raise HTTPException(
                    status_code=400,
                    detail="source_uri must be gs://... for this UI path. Use signed upload flow for local files.",
                )
            mapped = await _proxy_post(
                f"{INGEST_URL}/v1/connectors/gcs/import",
                {
                    "tenant": body.tenant,
                    "source_gcs_uri": source_uri,
                    "doc_id": body.doc_id,
                    "trace_id": body.trace_id,
                    "publish": True,
                },
                auth=authorization,
            )
            return {
                "job_id": mapped.get("doc_id"),
                "doc_id": mapped.get("doc_id"),
                "status": mapped.get("status"),
                "tenant": mapped.get("tenant"),
                "trace_id": mapped.get("trace_id"),
                "source_uri": mapped.get("source_gcs_uri"),
                "raw_gcs_uri": mapped.get("raw_gcs_uri"),
                "published": mapped.get("published"),
                "pubsub_message_id": mapped.get("pubsub_message_id"),
                "raw": mapped,
            }

        payload = {
            "filename": body.filename or "upload.bin",
            "content_type": body.content_type or "application/octet-stream",
            "size": body.size or 0,
            "tenant": body.tenant,
            "doc_id": body.doc_id,
            "trace_id": body.trace_id,
        }
        return await _proxy_post(f"{INGEST_URL}/v1/ingest", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/ingest/complete")
async def api_ingest_complete(body: IngestCompleteRequest, authorization: str | None = Header(default=None)):
    try:
        payload = {
            "doc_id": body.doc_id or body.job_id,
            "tenant": body.tenant,
            "trace_id": body.trace_id,
            "gcs_uri": body.gcs_uri,
            "force_reprocess": body.force_reprocess,
        }
        return await _proxy_post(f"{INGEST_URL}/v1/ingest/complete", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.get("/api/v1/doc/{doc_id}")
async def api_get_doc(doc_id: str, authorization: str | None = Header(default=None)):
    try:
        data = await _proxy_get(f"{INGEST_URL}/v1/doc/{doc_id}", auth=authorization)
        job = data.get("job") or {}
        metrics = job.get("metrics") or {}
        chunk_count = (
            metrics.get("chunk_count")
            or metrics.get("chunks")
            or metrics.get("chunks_indexed")
            or metrics.get("total_chunks")
        )
        return {
            "job_id": job.get("job_id") or data.get("doc_id"),
            "doc_id": data.get("doc_id"),
            "status": (job.get("status") or "UNKNOWN").upper(),
            "tenant": data.get("tenant"),
            "source_uri": data.get("source_uri"),
            "chunk_count": chunk_count,
            "updated_at": data.get("updated_at"),
            "error": job.get("error"),
            "job": job,
            "raw": data,
        }
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


# ==================== CONNECTORS ====================

@app.post("/api/v1/connectors/gcs/import")
async def api_gcs_import(body: GCSImportRequest, authorization: str | None = Header(default=None)):
    try:
        source_gcs_uri = body.source_gcs_uri
        if not source_gcs_uri and body.bucket:
            if not body.prefix:
                raise HTTPException(
                    status_code=400,
                    detail="When using bucket mode, prefix must be a full object path.",
                )
            source_gcs_uri = f"gs://{body.bucket.strip().rstrip('/')}/{body.prefix.strip().lstrip('/')}"

        mapped = await _proxy_post(
            f"{INGEST_URL}/v1/connectors/gcs/import",
            {
                "tenant": body.tenant,
                "source_gcs_uri": source_gcs_uri,
                "doc_id": body.doc_id,
                "trace_id": body.trace_id,
                "force_reprocess": body.force_reprocess,
                "publish": body.publish,
            },
            auth=authorization,
        )

        return {
            "jobs_queued": 1 if mapped.get("published") else 0,
            "tenant": mapped.get("tenant"),
            "bucket": body.bucket,
            "prefix": body.prefix,
            "doc_id": mapped.get("doc_id"),
            "status": mapped.get("status"),
            "trace_id": mapped.get("trace_id"),
            "source_gcs_uri": mapped.get("source_gcs_uri"),
            "raw_gcs_uri": mapped.get("raw_gcs_uri"),
            "raw": mapped,
        }
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise _gw_err(exc)


# ==================== QUERY ====================

@app.post("/api/v1/query")
async def api_query(body: QueryRequest, authorization: str | None = Header(default=None)):
    try:
        raw = await _proxy_post(
            f"{RAG_URL}/v1/query",
            {"tenant": body.tenant, "query": body.query, "top_k": body.k, "doc_ids": body.doc_ids},
            auth=authorization,
        )
        answers = raw.get("answers") or []
        best = answers[0] if answers else {}
        citations = best.get("citations") or []
        return {
            "answer": best.get("text", ""),
            "score": best.get("score"),
            "citations": citations,
            "answers": answers,
            "trace_id": raw.get("trace_id"),
            "raw": raw,
        }
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


# ==================== DECISIONS ====================

def _legacy_decision_payload(body: DecisionRequest) -> dict[str, Any]:
    context = dict(body.context or {})
    metadata = dict(body.metadata or {})
    metadata.setdefault("decision_type", body.decision_type)
    if body.subject_id:
        metadata.setdefault("subject_id", body.subject_id)

    citations = body.citations or []
    context_docs = _unique_strings([item.get("doc_id") for item in citations if isinstance(item, dict)])
    context_chunks = _unique_strings([item.get("chunk_id") for item in citations if isinstance(item, dict)])
    context_docs.extend(_unique_strings(context.get("context_docs")))
    context_chunks.extend(_unique_strings(context.get("context_chunks")))
    context_docs = _unique_strings(context_docs)
    context_chunks = _unique_strings(context_chunks)

    if not context_docs:
        raise HTTPException(status_code=400, detail="At least one context doc_id is required in citations/context_docs.")

    return {
        "decision_id": body.trace_id,
        "tenant": body.tenant,
        "trace_id": body.trace_id,
        "model": _first_non_empty([context.get("model"), metadata.get("model")], default="unknown-model"),
        "model_version": _first_non_empty([context.get("model_version"), metadata.get("model_version")], default=""),
        "input": _first_non_empty([context.get("query"), context.get("input"), metadata.get("input")], default=body.decision_type),
        "output": _first_non_empty([context.get("answer"), context.get("output"), metadata.get("output")], default=body.decision_type),
        "confidence": context.get("confidence", metadata.get("confidence")),
        "context_docs": context_docs,
        "context_chunks": context_chunks,
        "metadata": metadata,
    }


def _legacy_decision_query_payload(body: DecisionQueryRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"tenant": body.tenant, "limit": body.limit}
    if body.trace_id:
        payload["decision_trace_id"] = body.trace_id
    if body.from_date:
        payload["created_from"] = _date_floor(body.from_date)
    if body.to_date:
        payload["created_to"] = _date_ceil(body.to_date)

    text_tokens: list[str] = []
    if body.subject_id:
        text_tokens.append(body.subject_id)
    if body.decision_type:
        text_tokens.append(body.decision_type)
    if text_tokens:
        payload["query"] = " ".join(text_tokens)
    return payload


def _compat_decisions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        metadata = item.get("metadata") or {}
        citations = []
        for chunk_id in item.get("context_chunks") or []:
            citations.append({"chunk_id": chunk_id})
        for doc_id in item.get("context_docs") or []:
            citations.append({"doc_id": doc_id})
        out.append(
            {
                **item,
                "decision_type": metadata.get("decision_type"),
                "subject_id": metadata.get("subject_id"),
                "citations": citations,
            }
        )
    return out


def _normalize_decision_artifact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    if "trace_ids" in normalized and "decision_ids" not in normalized:
        normalized["decision_ids"] = normalized.pop("trace_ids")
    return normalized


def _normalize_verify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    if "checksum" in normalized and "expected_report_hash_sha256" not in normalized:
        normalized["expected_report_hash_sha256"] = normalized.pop("checksum")
    if "artifact_uri" in normalized and "gs_uri" not in normalized:
        normalized["gs_uri"] = normalized.pop("artifact_uri")
    if "artifact_id" in normalized and "gs_uri" not in normalized:
        raise HTTPException(
            status_code=400,
            detail="verify requires gs_uri (artifact_id-only payload is not supported by current API).",
        )
    return normalized


@app.post("/api/v1/decisions")
async def api_register_decision(body: DecisionRequest, authorization: str | None = Header(default=None)):
    try:
        payload = _legacy_decision_payload(body)
        return await _proxy_post(f"{INGEST_URL}/v1/decisions", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/decisions/query")
async def api_query_decisions(body: DecisionQueryRequest, authorization: str | None = Header(default=None)):
    try:
        raw = await _proxy_post(f"{INGEST_URL}/v1/decisions/query", _legacy_decision_query_payload(body), auth=authorization)
        decisions = _compat_decisions(raw.get("decisions") or [])
        return {
            "trace_id": raw.get("trace_id"),
            "total": raw.get("total", len(decisions)),
            "returned": raw.get("returned", len(decisions)),
            "offset": raw.get("offset", 0),
            "limit": raw.get("limit", body.limit),
            "decisions": decisions,
            "items": decisions,
            "raw": raw,
        }
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.get("/api/v1/decisions/report")
async def api_decisions_report(
    tenant: str,
    decision_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    authorization: str | None = Header(default=None),
):
    try:
        if decision_id:
            return await _proxy_get(
                f"{INGEST_URL}/v1/decisions/{decision_id}/report",
                params={"tenant": tenant},
                auth=authorization,
            )

        raw = await _proxy_post(
            f"{INGEST_URL}/v1/decisions/query",
            {"tenant": tenant, "created_from": _date_floor(from_date), "created_to": _date_ceil(to_date), "limit": 100},
            auth=authorization,
        )
        decisions = _compat_decisions(raw.get("decisions") or [])
        return {
            "trace_id": raw.get("trace_id"),
            "tenant": tenant,
            "from_date": from_date,
            "to_date": to_date,
            "total": raw.get("total", len(decisions)),
            "returned": raw.get("returned", len(decisions)),
            "decisions": decisions,
            "note": "This is a compatibility summary. Use decision_id for per-decision report.",
        }
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/decisions/export")
async def api_decisions_export(body: dict[str, Any], authorization: str | None = Header(default=None)):
    try:
        payload = _normalize_decision_artifact_payload(body)
        return await _proxy_post(f"{INGEST_URL}/v1/decisions/export", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/decisions/bundle")
async def api_decisions_bundle(body: dict[str, Any], authorization: str | None = Header(default=None)):
    try:
        payload = _normalize_decision_artifact_payload(body)
        return await _proxy_post(f"{INGEST_URL}/v1/decisions/bundle", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/decisions/package")
async def api_decisions_package(body: dict[str, Any], authorization: str | None = Header(default=None)):
    try:
        payload = _normalize_decision_artifact_payload(body)
        return await _proxy_post(f"{INGEST_URL}/v1/decisions/package", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/decisions/verify")
async def api_decisions_verify(body: dict[str, Any], authorization: str | None = Header(default=None)):
    try:
        payload = _normalize_verify_payload(body)
        return await _proxy_post(f"{INGEST_URL}/v1/decisions/verify", payload, auth=authorization)
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise _gw_err(exc)


# ==================== GOVERNANCE ====================

def _retention_payload(body: RetentionPolicyRequest) -> dict[str, Any]:
    return {
        "tenant": body.tenant,
        "artifact_type": body.artifact_type or "audit_artifacts",
        "retain_days": body.retention_days,
        "legal_hold_enabled": True,
        "immutable_required": True,
    }


def _legal_hold_payload(body: LegalHoldRequest) -> dict[str, Any]:
    doc_ids = _unique_strings(body.doc_ids)
    scope_type = "tenant"
    scope_id = body.tenant
    if doc_ids:
        scope_type = "doc_id"
        scope_id = doc_ids[0]
    reason = body.reason
    if body.hold_name:
        reason = f"{body.hold_name}: {reason}"
    return {
        "tenant": body.tenant,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "reason": reason,
        "case_id": (body.query_filter or {}).get("case_id") if body.query_filter else None,
        "regulator_ref": (body.query_filter or {}).get("regulator_ref") if body.query_filter else None,
    }


@app.post("/api/v1/admin/retention-policies")
async def api_create_retention_policy(
    body: RetentionPolicyRequest,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        return await _proxy_post(
            f"{INGEST_URL}/v1/admin/retention-policies",
            _retention_payload(body),
            auth=authorization,
            admin_key=admin_key,
        )
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.get("/api/v1/admin/retention-policies")
async def api_list_retention_policies(
    tenant: str,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        raw = await _proxy_get(
            f"{INGEST_URL}/v1/admin/retention-policies",
            params={"tenant": tenant},
            auth=authorization,
            admin_key=admin_key,
        )
        policies = raw.get("policies") or []
        compat_policies = []
        for item in policies:
            compat_policies.append(
                {
                    **item,
                    "policy_name": item.get("artifact_type"),
                    "retention_days": item.get("retain_days"),
                    "doc_types": [item.get("artifact_type")] if item.get("artifact_type") else [],
                    "action": "delete",
                    "policy_id": item.get("artifact_type"),
                }
            )
        return {**raw, "policies": compat_policies}
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.delete("/api/v1/admin/retention-policies/{policy_id}")
async def api_delete_retention_policy(policy_id: str):
    raise HTTPException(
        status_code=405,
        detail=f"Policy deletion is not exposed by current backend API (requested policy_id={policy_id}).",
    )


@app.post("/api/v1/admin/legal-holds")
async def api_create_legal_hold(
    body: LegalHoldRequest,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        return await _proxy_post(
            f"{INGEST_URL}/v1/admin/legal-holds",
            _legal_hold_payload(body),
            auth=authorization,
            admin_key=admin_key,
        )
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.get("/api/v1/admin/legal-holds")
async def api_list_legal_holds(
    tenant: str,
    active_only: bool = True,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        raw = await _proxy_get(
            f"{INGEST_URL}/v1/admin/legal-holds",
            params={"tenant": tenant, "active_only": str(active_only).lower()},
            auth=authorization,
            admin_key=admin_key,
        )
        holds = raw.get("holds") or []
        compat_holds = []
        for item in holds:
            doc_ids: list[str] = []
            if item.get("scope_type") == "doc_id" and item.get("scope_id"):
                doc_ids.append(item["scope_id"])
            compat_holds.append(
                {
                    **item,
                    "id": item.get("hold_id"),
                    "hold_name": item.get("hold_id"),
                    "doc_ids": doc_ids,
                }
            )
        return {**raw, "holds": compat_holds}
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.delete("/api/v1/admin/legal-holds/{hold_id}")
async def api_delete_legal_hold(
    hold_id: str,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        return await _proxy_post(
            f"{INGEST_URL}/v1/admin/legal-holds/release",
            {"hold_id": hold_id},
            auth=authorization,
            admin_key=admin_key,
        )
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


@app.post("/api/v1/admin/retention/enforce")
async def api_enforce_retention(
    body: RetentionEnforceRequest,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
):
    try:
        admin_key = _effective_admin_key(x_admin_key)
        return await _proxy_post(
            f"{INGEST_URL}/v1/admin/retention/enforce",
            body.model_dump(exclude_none=True),
            auth=authorization,
            admin_key=admin_key,
        )
    except requests.HTTPError as exc:
        raise _http_err(exc)
    except Exception as exc:
        raise _gw_err(exc)


# ==================== HEALTH ====================

@app.get("/api/v1/health")
async def api_health_all():
    results: dict[str, dict[str, Any]] = {}
    for svc, base_url in [("ingest", INGEST_URL), ("processor", PROCESSOR_URL), ("rag", RAG_URL)]:
        try:
            start = time.perf_counter()
            resp = requests.get(f"{base_url}/v1/healthz", timeout=5)
            latency_ms = round((time.perf_counter() - start) * 1000)
            results[svc] = {
                "status": "healthy" if resp.status_code == 200 else "degraded",
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            results[svc] = {"status": "unreachable", "error": str(exc)}
    overall = "healthy" if all(item.get("status") == "healthy" for item in results.values()) else "degraded"
    return {"overall": overall, "services": results}


# ==================== SETTINGS API ====================

@app.post("/api/v1/auth/test-token")
async def api_auth_test_token():
    return _mint_auth0_test_token()


@app.get("/api/settings")
async def api_get_settings():
    return {
        "ingest_url": INGEST_URL,
        "processor_url": PROCESSOR_URL,
        "rag_url": RAG_URL,
        "decisions_and_governance_url": INGEST_URL,
        "admin_key_configured": bool(ADMIN_KEY),
        "deploy_env": DASHBOARD_DEPLOY_ENV,
        "test_token_requested": DASHBOARD_ENABLE_TEST_TOKEN,
        "test_token_enabled": DASHBOARD_TEST_TOKEN_ENABLED,
    }


# ==================== SERVER ====================

def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn

    uvicorn.run(app, host=host, port=port)
