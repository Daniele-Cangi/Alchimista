from services.shared.config import RuntimeConfig
from services.shared.embeddings import build_embedder, deterministic_embedding, project_embedding


def test_project_embedding_reduces_dimensions_and_normalizes() -> None:
    values = [float(idx + 1) for idx in range(20)]
    projected = project_embedding(values, 8)
    assert len(projected) == 8
    norm = sum(item * item for item in projected) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_project_embedding_pads_short_vectors() -> None:
    projected = project_embedding([0.5, -0.5], 5)
    assert len(projected) == 5
    norm = sum(item * item for item in projected) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_build_embedder_deterministic_backend() -> None:
    config = RuntimeConfig(
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
        embedding_dimensions=32,
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

    embedder = build_embedder(config)
    first = embedder("hello world")
    second = embedder("hello world")
    expected = deterministic_embedding("hello world", 32)
    assert len(first) == 32
    assert first == second
    assert first == expected
