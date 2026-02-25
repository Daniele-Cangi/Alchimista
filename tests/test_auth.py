import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException
from starlette.requests import Request

import services.shared.auth as auth_module
from services.shared.auth import require_auth, require_pubsub_push_auth
from services.shared.config import RuntimeConfig


def test_require_auth_disabled_returns_none() -> None:
    config = _make_config(auth_enabled=False)
    request = _build_request("")
    assert require_auth(request, config=config, tenant="default") is None


def test_require_auth_hs256_success() -> None:
    config = _make_config(
        auth_enabled=True,
        auth_algorithms=("HS256",),
        auth_jwt_shared_secret="secret",
        auth_issuer="https://issuer.example",
        auth_audiences=("alchimista-api",),
        auth_require_tenant_claim=True,
    )
    token = _encode_hs256(
        payload={
            "sub": "vendor-user-1",
            "iss": "https://issuer.example",
            "aud": "alchimista-api",
            "tenant": "default",
            "exp": int(time.time()) + 300,
        },
        secret="secret",
    )
    request = _build_request(token)
    principal = require_auth(request, config=config, tenant="default")
    assert principal is not None
    assert principal.subject == "vendor-user-1"


def test_require_auth_rejects_tenant_mismatch() -> None:
    config = _make_config(
        auth_enabled=True,
        auth_algorithms=("HS256",),
        auth_jwt_shared_secret="secret",
        auth_issuer="https://issuer.example",
        auth_audiences=("alchimista-api",),
        auth_require_tenant_claim=True,
    )
    token = _encode_hs256(
        payload={
            "sub": "vendor-user-2",
            "iss": "https://issuer.example",
            "aud": "alchimista-api",
            "tenant": "default",
            "exp": int(time.time()) + 300,
        },
        secret="secret",
    )
    request = _build_request(token)
    try:
        require_auth(request, config=config, tenant="other")
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_require_pubsub_push_auth_success(monkeypatch) -> None:
    config = _make_config(
        auth_enabled=True,
        pubsub_push_auth_enabled=True,
        pubsub_push_audiences=("https://document-processor-service.example/v1/process/pubsub",),
        pubsub_push_service_accounts=("pubsub-push-sa@secure-electron-474908-k9.iam.gserviceaccount.com",),
    )
    token = _encode_rs256_for_test(
        payload={
            "sub": "service-994021588311@gcp-sa-pubsub.iam.gserviceaccount.com",
            "iss": "https://accounts.google.com",
            "aud": "https://document-processor-service.example/v1/process/pubsub",
            "email": "pubsub-push-sa@secure-electron-474908-k9.iam.gserviceaccount.com",
            "exp": int(time.time()) + 300,
        }
    )
    request = _build_request(token)
    monkeypatch.setattr(auth_module, "_verify_rs256_signature", lambda *args, **kwargs: None)
    principal = require_pubsub_push_auth(request, config=config)
    assert principal.subject == "service-994021588311@gcp-sa-pubsub.iam.gserviceaccount.com"
    assert principal.issuer == "https://accounts.google.com"


def test_require_pubsub_push_auth_rejects_service_account_mismatch(monkeypatch) -> None:
    config = _make_config(
        auth_enabled=True,
        pubsub_push_auth_enabled=True,
        pubsub_push_audiences=("https://document-processor-service.example/v1/process/pubsub",),
        pubsub_push_service_accounts=("allowed-sa@secure-electron-474908-k9.iam.gserviceaccount.com",),
    )
    token = _encode_rs256_for_test(
        payload={
            "sub": "service-994021588311@gcp-sa-pubsub.iam.gserviceaccount.com",
            "iss": "https://accounts.google.com",
            "aud": "https://document-processor-service.example/v1/process/pubsub",
            "email": "different-sa@secure-electron-474908-k9.iam.gserviceaccount.com",
            "exp": int(time.time()) + 300,
        }
    )
    request = _build_request(token)
    monkeypatch.setattr(auth_module, "_verify_rs256_signature", lambda *args, **kwargs: None)
    try:
        require_pubsub_push_auth(request, config=config)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403


def _make_config(**overrides: object) -> RuntimeConfig:
    base = RuntimeConfig(
        project_id="p",
        region="europe-west4",
        database_url="postgresql://unused",
        raw_bucket="raw",
        processed_bucket="processed",
        reports_bucket="reports",
        ingest_topic="doc-ingest-topic",
        ingest_dlq_topic="doc-ingest-topic-dlq",
        signed_url_expiration_minutes=15,
        default_tenant="default",
        enforce_storage_hardening=False,
        admin_api_key="",
        ingest_dlq_subscription="doc-ingest-topic-dlq-sub",
        processor_max_inflight=8,
        vector_backend="sql_embedding_scan",
        vertex_index_id="",
        vertex_index_endpoint_id="",
        vertex_deployed_index_id="",
        embedding_backend="deterministic_hash",
        embedding_dimensions=128,
        embedding_timeout_seconds=30,
        vertex_embedding_model="text-embedding-004",
        auth_enabled=False,
        auth_issuer="",
        auth_audiences=tuple(),
        auth_jwks_url="",
        auth_algorithms=("RS256",),
        auth_tenant_claims=("tenant", "tenants"),
        auth_require_tenant_claim=True,
        auth_jwt_shared_secret="",
        auth_allow_unauthenticated_pubsub=True,
        pubsub_push_auth_enabled=False,
        pubsub_push_audiences=tuple(),
        pubsub_push_service_accounts=tuple(),
    )
    return RuntimeConfig(**{**base.__dict__, **overrides})


def _build_request(token: str) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    return Request(scope)


def _encode_hs256(*, payload: dict[str, object], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_bytes = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    payload_bytes = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    signing_input = f"{header_bytes}.{payload_bytes}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_bytes = _b64url_encode(signature)
    return f"{header_bytes}.{payload_bytes}.{signature_bytes}"


def _encode_rs256_for_test(*, payload: dict[str, object]) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-kid"}
    header_bytes = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    payload_bytes = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    signature_bytes = _b64url_encode(b"fake-signature")
    return f"{header_bytes}.{payload_bytes}.{signature_bytes}"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
