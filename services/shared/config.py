from __future__ import annotations

import os
from dataclasses import dataclass


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return value or ""


def get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def get_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_env_csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default) or ""
    parts = [item.strip() for item in raw.split(",")]
    return tuple(item for item in parts if item)


@dataclass(frozen=True)
class RuntimeConfig:
    project_id: str
    region: str
    database_url: str
    raw_bucket: str
    processed_bucket: str
    reports_bucket: str
    ingest_topic: str
    ingest_dlq_topic: str
    signed_url_expiration_minutes: int
    default_tenant: str
    enforce_storage_hardening: bool
    admin_api_key: str
    ingest_dlq_subscription: str
    processor_max_inflight: int
    vector_backend: str
    vertex_index_id: str
    vertex_index_endpoint_id: str
    vertex_deployed_index_id: str
    embedding_backend: str
    embedding_dimensions: int
    embedding_timeout_seconds: int
    vertex_embedding_model: str
    auth_enabled: bool
    auth_issuer: str
    auth_audiences: tuple[str, ...]
    auth_jwks_url: str
    auth_algorithms: tuple[str, ...]
    auth_tenant_claims: tuple[str, ...]
    auth_require_tenant_claim: bool
    auth_jwt_shared_secret: str
    auth_allow_unauthenticated_pubsub: bool



def load_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        project_id=get_env("PROJECT_ID", required=True),
        region=get_env("REGION", "europe-west4"),
        database_url=get_env("DATABASE_URL", required=True),
        raw_bucket=get_env("RAW_BUCKET", ""),
        processed_bucket=get_env("PROCESSED_BUCKET", ""),
        reports_bucket=get_env("REPORTS_BUCKET", ""),
        ingest_topic=get_env("INGEST_TOPIC", "doc-ingest-topic"),
        ingest_dlq_topic=get_env("INGEST_DLQ_TOPIC", "doc-ingest-topic-dlq"),
        signed_url_expiration_minutes=get_env_int("SIGNED_URL_EXPIRATION_MINUTES", 15),
        default_tenant=get_env("DEFAULT_TENANT", "default"),
        enforce_storage_hardening=get_env_bool("ENFORCE_STORAGE_HARDENING", False),
        admin_api_key=get_env("ADMIN_API_KEY", ""),
        ingest_dlq_subscription=get_env("INGEST_DLQ_SUBSCRIPTION", "doc-ingest-topic-dlq-sub"),
        processor_max_inflight=max(1, get_env_int("PROCESSOR_MAX_INFLIGHT", 8)),
        vector_backend=get_env("VECTOR_BACKEND", "sql_embedding_scan"),
        vertex_index_id=get_env("VERTEX_INDEX_ID", ""),
        vertex_index_endpoint_id=get_env("VERTEX_INDEX_ENDPOINT_ID", ""),
        vertex_deployed_index_id=get_env("VERTEX_DEPLOYED_INDEX_ID", ""),
        embedding_backend=get_env("EMBEDDING_BACKEND", "deterministic_hash"),
        embedding_dimensions=max(8, get_env_int("EMBEDDING_DIMENSIONS", 128)),
        embedding_timeout_seconds=max(1, get_env_int("EMBEDDING_TIMEOUT_SECONDS", 30)),
        vertex_embedding_model=get_env("VERTEX_EMBEDDING_MODEL", "text-embedding-004"),
        auth_enabled=get_env_bool("AUTH_ENABLED", False),
        auth_issuer=get_env("AUTH_ISSUER", ""),
        auth_audiences=get_env_csv("AUTH_AUDIENCE", ""),
        auth_jwks_url=get_env("AUTH_JWKS_URL", ""),
        auth_algorithms=get_env_csv("AUTH_ALGORITHMS", "RS256"),
        auth_tenant_claims=get_env_csv("AUTH_TENANT_CLAIMS", "tenant,tenants"),
        auth_require_tenant_claim=get_env_bool("AUTH_REQUIRE_TENANT_CLAIM", True),
        auth_jwt_shared_secret=get_env("AUTH_JWT_SHARED_SECRET", ""),
        auth_allow_unauthenticated_pubsub=get_env_bool("AUTH_ALLOW_UNAUTHENTICATED_PUBSUB", True),
    )
