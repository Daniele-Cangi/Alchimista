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
    pubsub_push_auth_enabled: bool
    pubsub_push_audiences: tuple[str, ...]
    pubsub_push_service_accounts: tuple[str, ...]
    audit_report_signing_key: str
    audit_report_signing_key_id: str
    profile: str = "local"
    deploy_environment: str = "development"
    storage_backend: str = "filesystem"
    local_storage_path: str = "/data/objects"
    queue_backend: str = "direct_http"
    processor_url: str = "http://document-processor-service:8080"
    auth_mode: str = ""
    local_auth_token: str = ""
    local_auth_tenants: tuple[str, ...] = ("*",)
    privacy_policy: str = "off"
    privacy_service_url: str = "http://privacy-service:8080"
    privacy_service_token: str = ""
    privacy_timeout_seconds: int = 30
    privacy_mapping_enabled: bool = True
    privacy_vault_key: str = ""
    privacy_vault_key_version: str = "v1"
    privacy_detector: str = "rizzo_regex"
    privacy_fail_closed: bool = True



def load_runtime_config() -> RuntimeConfig:
    profile = get_env("ALCHIMISTA_PROFILE", "local").strip().lower()
    if profile not in {"local", "gcp"}:
        raise RuntimeError("ALCHIMISTA_PROFILE must be 'local' or 'gcp'")

    deploy_environment = get_env(
        "ALCHIMISTA_ENV",
        get_env("ENVIRONMENT", "development"),
    ).strip().lower()
    storage_backend = get_env("STORAGE_BACKEND", "filesystem" if profile == "local" else "gcs").strip().lower()
    queue_backend = get_env("QUEUE_BACKEND", "direct_http" if profile == "local" else "pubsub").strip().lower()

    auth_mode_raw = os.getenv("AUTH_MODE")
    if auth_mode_raw is not None and auth_mode_raw.strip():
        auth_mode = auth_mode_raw.strip().lower()
    elif os.getenv("AUTH_ENABLED") is not None:
        auth_mode = "oidc" if get_env_bool("AUTH_ENABLED", False) else "disabled"
    else:
        auth_mode = "local" if profile == "local" else "oidc"

    if storage_backend not in {"filesystem", "gcs"}:
        raise RuntimeError("STORAGE_BACKEND must be 'filesystem' or 'gcs'")
    if queue_backend not in {"direct_http", "pubsub"}:
        raise RuntimeError("QUEUE_BACKEND must be 'direct_http' or 'pubsub'")
    if auth_mode not in {"local", "oidc", "disabled"}:
        raise RuntimeError("AUTH_MODE must be 'local', 'oidc', or 'disabled'")
    if auth_mode == "disabled" and deploy_environment in {"prod", "production", "external"}:
        raise RuntimeError("AUTH_MODE=disabled is not allowed in production/external environments")

    project_id = get_env("PROJECT_ID", "")
    if profile == "gcp" and not project_id:
        raise RuntimeError("PROJECT_ID is required for ALCHIMISTA_PROFILE=gcp")
    if (storage_backend == "gcs" or queue_backend == "pubsub") and not project_id:
        raise RuntimeError("PROJECT_ID is required by the selected GCP adapter")

    local_auth_token = get_env("LOCAL_AUTH_TOKEN", get_env("ALCHIMISTA_API_TOKEN", ""))
    if auth_mode == "local" and len(local_auth_token) < 24:
        raise RuntimeError("LOCAL_AUTH_TOKEN/ALCHIMISTA_API_TOKEN must contain at least 24 characters")

    privacy_policy = get_env("PRIVACY_POLICY", "off").strip().lower()
    if privacy_policy not in {"off", "detect", "protect_egress", "strict"}:
        raise RuntimeError("PRIVACY_POLICY must be off, detect, protect_egress, or strict")
    privacy_service_token = get_env("PRIVACY_SERVICE_TOKEN", "")
    if privacy_policy != "off" and len(privacy_service_token) < 24:
        raise RuntimeError("PRIVACY_SERVICE_TOKEN must contain at least 24 characters when privacy is enabled")

    return RuntimeConfig(
        project_id=project_id,
        region=get_env("REGION", "europe-west4"),
        database_url=get_env("DATABASE_URL", required=True),
        raw_bucket=get_env("RAW_BUCKET", "raw" if storage_backend == "filesystem" else ""),
        processed_bucket=get_env("PROCESSED_BUCKET", "processed" if storage_backend == "filesystem" else ""),
        reports_bucket=get_env("REPORTS_BUCKET", "reports" if storage_backend == "filesystem" else ""),
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
        auth_enabled=auth_mode != "disabled",
        auth_issuer=get_env("AUTH_ISSUER", ""),
        auth_audiences=get_env_csv("AUTH_AUDIENCE", ""),
        auth_jwks_url=get_env("AUTH_JWKS_URL", ""),
        auth_algorithms=get_env_csv("AUTH_ALGORITHMS", "RS256"),
        auth_tenant_claims=get_env_csv("AUTH_TENANT_CLAIMS", "tenant,tenants"),
        auth_require_tenant_claim=get_env_bool("AUTH_REQUIRE_TENANT_CLAIM", True),
        auth_jwt_shared_secret=get_env("AUTH_JWT_SHARED_SECRET", ""),
        auth_allow_unauthenticated_pubsub=get_env_bool("AUTH_ALLOW_UNAUTHENTICATED_PUBSUB", True),
        pubsub_push_auth_enabled=get_env_bool("PUBSUB_PUSH_AUTH_ENABLED", False),
        pubsub_push_audiences=get_env_csv("PUBSUB_PUSH_AUDIENCE", ""),
        pubsub_push_service_accounts=get_env_csv("PUBSUB_PUSH_SERVICE_ACCOUNTS", ""),
        audit_report_signing_key=get_env("AUDIT_REPORT_SIGNING_KEY", ""),
        audit_report_signing_key_id=get_env("AUDIT_REPORT_SIGNING_KEY_ID", ""),
        profile=profile,
        deploy_environment=deploy_environment,
        storage_backend=storage_backend,
        local_storage_path=get_env("LOCAL_STORAGE_PATH", "/data/objects"),
        queue_backend=queue_backend,
        processor_url=get_env("PROCESSOR_URL", "http://document-processor-service:8080"),
        auth_mode=auth_mode,
        local_auth_token=local_auth_token,
        local_auth_tenants=get_env_csv("LOCAL_AUTH_TENANTS", "*"),
        privacy_policy=privacy_policy,
        privacy_service_url=get_env("PRIVACY_SERVICE_URL", "http://privacy-service:8080"),
        privacy_service_token=privacy_service_token,
        privacy_timeout_seconds=max(1, get_env_int("PRIVACY_TIMEOUT_SECONDS", 30)),
        privacy_mapping_enabled=get_env_bool("PRIVACY_MAPPING_ENABLED", True),
        privacy_vault_key=get_env("PRIVACY_VAULT_KEY", ""),
        privacy_vault_key_version=get_env("PRIVACY_VAULT_KEY_VERSION", "v1"),
        privacy_detector=get_env("PRIVACY_DETECTOR", "rizzo_regex"),
        privacy_fail_closed=get_env_bool("PRIVACY_FAIL_CLOSED", True),
    )
