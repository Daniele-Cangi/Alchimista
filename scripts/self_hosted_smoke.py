#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


SYNTHETIC_EMAIL = "alice@example.invalid"
SYNTHETIC_IBAN = "IT60X0542811101000000123456"
SYNTHETIC_CARD = "4111 1111 1111 1111"
SYNTHETIC_TEXT = (
    "Synthetic privacy fixture only. "
    f"Email {SYNTHETIC_EMAIL}; IBAN {SYNTHETIC_IBAN}; card {SYNTHETIC_CARD}. "
    "Alchimista smoke evidence says the retention policy is thirty days."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the self-hosted Alchimista vertical slice")
    parser.add_argument("--verify-restart", action="store_true", help="restart PostgreSQL and verify persistence")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    env = _load_env(root / ".env")
    api_token = env.get("ALCHIMISTA_API_TOKEN") or os.getenv("ALCHIMISTA_API_TOKEN", "")
    privacy_token = env.get("PRIVACY_SERVICE_TOKEN") or os.getenv("PRIVACY_SERVICE_TOKEN", "")
    smoke_database_url = os.getenv("SMOKE_DATABASE_URL", "").strip()
    compose = _compose_command()
    if not api_token or not privacy_token:
        raise RuntimeError("Generate .env with: python scripts/init_local_env.py")

    auth_headers = {"Authorization": f"Bearer {api_token}"}
    privacy_headers = {"x-privacy-token": privacy_token}
    doc_id = f"smoke-{uuid.uuid4().hex[:12]}"
    smoke_text = f"{SYNTHETIC_TEXT} Synthetic run marker {doc_id}."

    _wait_json("http://127.0.0.1:8011/v1/readyz")
    _wait_json("http://127.0.0.1:8013/v1/readyz")
    _wait_json("http://127.0.0.1:8014/v1/privacy/ready")
    dashboard_health = _wait_json("http://127.0.0.1:8000/api/v1/health")
    if (dashboard_health.get("services") or {}).get("privacy", {}).get("status") != "healthy":
        raise AssertionError("localhost product health does not include a healthy privacy service")
    home_html = _get_text("http://127.0.0.1:8000/")
    if "Alchimista" not in home_html or "Documenti" not in home_html or "Privacy" not in home_html:
        raise AssertionError("localhost root is not the Alchimista product shell")
    _expect_http_status(
        "PUT",
        "http://127.0.0.1:8000/api/v1/privacy/settings",
        {
            "workspace": "default",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_http",
            "privacy_mapping_enabled": True,
        },
        409,
    )
    selected_privacy = _put_json(
        "http://127.0.0.1:8000/api/v1/privacy/settings",
        {
            "workspace": "default",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_regex",
            "privacy_mapping_enabled": True,
        },
    )
    if selected_privacy.get("privacy_policy") != "strict":
        raise AssertionError("runtime privacy policy did not persist through the product control API")

    ingest = _post_multipart(
        "http://127.0.0.1:8011/v1/ingest",
        fields={"tenant": "default", "doc_id": doc_id},
        filename="synthetic-privacy-smoke.txt",
        content=smoke_text.encode("utf-8"),
        headers=auth_headers,
    )
    if ingest.get("doc_id") != doc_id:
        raise AssertionError("ingestion did not return the requested synthetic doc_id")

    status = _poll_document(doc_id, auth_headers)
    if ((status.get("job") or {}).get("status")) != "SUCCEEDED":
        raise AssertionError("document processing did not succeed")

    documents = _get_json("http://127.0.0.1:8000/api/v1/documents?workspace=default")
    listed = {item.get("doc_id"): item for item in documents.get("documents") or []}
    if doc_id not in listed:
        raise AssertionError("processed document did not appear in the localhost Documents view")
    if listed[doc_id].get("privacy_policy") != "strict":
        raise AssertionError("Documents view did not expose the applied privacy policy")
    detail = _get_json(f"http://127.0.0.1:8000/api/v1/documents/{doc_id}?workspace=default")
    if not detail.get("evidence") or int(detail.get("pii_detected") or 0) < 1:
        raise AssertionError("document detail is missing indexed evidence or privacy summary")

    query = _post_json(
        "http://127.0.0.1:8013/v1/query",
        {"tenant": "default", "query": "What is the retention policy?", "top_k": 3, "doc_ids": [doc_id]},
        auth_headers,
    )
    answers = query.get("answers") or []
    citations = (answers[0].get("citations") if answers else None) or []
    if not citations:
        raise AssertionError("RAG response did not contain citations")
    product_query = _post_json(
        "http://127.0.0.1:8000/api/v1/query",
        {"tenant": "default", "query": "What is the retention policy?", "k": 3, "doc_ids": [doc_id]},
    )
    product_citations = product_query.get("citations") or []
    if not product_query.get("answer") or not product_citations:
        raise AssertionError("localhost Ask path did not return an answer with evidence")
    if not product_citations[0].get("document_name") or product_citations[0].get("preview") is None:
        raise AssertionError("localhost Ask citation is not interactive evidence")
    chunk_ids = [item["chunk_id"] for item in citations]
    cross_tenant = _post_json(
        "http://127.0.0.1:8013/v1/query",
        {"tenant": "other-tenant", "query": "retention policy", "top_k": 3, "doc_ids": [doc_id]},
        auth_headers,
    )
    if cross_tenant.get("answers"):
        raise AssertionError("tenant boundary leaked retrieval chunks")

    protected = _post_json(
        "http://127.0.0.1:8014/v1/privacy/pseudonymize",
        {
            "text": smoke_text,
            "tenant": "default",
            "doc_id": doc_id,
            "reversible": True,
            "persist_mapping": True,
        },
        privacy_headers,
    )
    protected_text = str(protected.get("protected_text") or "")
    if any(raw in protected_text for raw in (SYNTHETIC_EMAIL, SYNTHETIC_IBAN, SYNTHETIC_CARD)):
        raise AssertionError("pseudonymized response contains raw synthetic PII")
    pii_types = set(protected.get("pii_types") or [])
    if not {"EMAIL", "IBAN", "CREDITCARDNUMBER"}.issubset(pii_types):
        raise AssertionError("expected synthetic PII classes were not detected")

    restored = _post_json(
        "http://127.0.0.1:8014/v1/privacy/restore",
        {"text": protected_text, "tenant": "default", "doc_id": doc_id},
        privacy_headers,
    )
    if restored.get("restored_text") != smoke_text:
        raise AssertionError("reversible placeholders did not restore exactly")

    lifecycle_doc_id = f"vault-lifecycle-{uuid.uuid4().hex[:12]}"
    _database_execute(
        compose,
        smoke_database_url,
        "INSERT INTO documents (doc_id, tenant, source_uri, mime_type) "
        "VALUES (%s, 'default', 'local://smoke/lifecycle', 'text/plain')",
        lifecycle_doc_id,
    )
    lifecycle_mapping = _post_json(
        "http://127.0.0.1:8014/v1/privacy/pseudonymize",
        {
            "text": "Synthetic lifecycle fixture orphan@example.invalid",
            "tenant": "default",
            "doc_id": lifecycle_doc_id,
            "reversible": True,
            "persist_mapping": True,
        },
        privacy_headers,
    )
    if not lifecycle_mapping.get("mapping_stored"):
        raise AssertionError("vault lifecycle fixture did not create a reversible mapping")
    mapping_count = _database_scalar(
        compose, smoke_database_url, "SELECT count(*) FROM pii_vault WHERE doc_id = %s", lifecycle_doc_id
    )
    if mapping_count == "0":
        raise AssertionError("vault lifecycle fixture did not persist a mapping")
    _database_execute(
        compose, smoke_database_url, "DELETE FROM documents WHERE doc_id = %s", lifecycle_doc_id
    )
    mapping_count = _database_scalar(
        compose, smoke_database_url, "SELECT count(*) FROM pii_vault WHERE doc_id = %s", lifecycle_doc_id
    )
    if mapping_count != "0":
        raise AssertionError("document deletion left orphaned privacy vault mappings")

    decision_id = f"decision-{uuid.uuid4().hex[:12]}"
    _post_json(
        "http://127.0.0.1:8011/v1/decisions",
        {
            "decision_id": decision_id,
            "model": "self-hosted-smoke",
            "model_version": "1",
            "input": f"Review request for {SYNTHETIC_EMAIL}",
            "output": "retain for thirty days",
            "confidence": 0.91,
            "context_docs": [doc_id],
            "context_chunks": chunk_ids,
            "tenant": "default",
        },
        auth_headers,
    )
    report = _get_json(
        f"http://127.0.0.1:8011/v1/decisions/{decision_id}/report?tenant=default",
        auth_headers,
    )
    report_json = json.dumps(report, sort_keys=True)
    if SYNTHETIC_EMAIL in report_json:
        raise AssertionError("audit report contains raw synthetic PII")
    privacy_evidence = ((report.get("decision") or {}).get("metadata") or {}).get("privacy") or {}
    if privacy_evidence.get("privacy_policy") not in {"detect", "protect_egress", "strict"}:
        raise AssertionError("audit report is missing privacy policy evidence")
    if privacy_evidence.get("mapping_exported") is not False:
        raise AssertionError("audit evidence must state that mappings were not exported")

    entity_count = _database_scalar(
        compose, smoke_database_url, "SELECT count(*) FROM entities WHERE doc_id = %s", doc_id
    )
    if entity_count != "0":
        raise AssertionError("privacy-enabled processing wrote raw legacy entities")
    audit_raw_count = _database_scalar(
        compose,
        smoke_database_url,
        "SELECT count(*) FROM ai_decisions WHERE decision_id = %s AND (input_text LIKE '%%alice@example.invalid%%' OR output_text LIKE '%%alice@example.invalid%%')",
        decision_id,
    )
    if audit_raw_count != "0":
        raise AssertionError("raw synthetic PII entered decision evidence")
    findings_raw_count = _database_scalar(
        compose,
        smoke_database_url,
        "SELECT count(*) FROM pii_findings WHERE doc_id = %s AND row_to_json(pii_findings)::text LIKE '%%alice@example.invalid%%'",
        doc_id,
    )
    if findings_raw_count != "0":
        raise AssertionError("raw synthetic PII entered privacy findings")
    vault_raw_count = _database_scalar(
        compose,
        smoke_database_url,
        "SELECT count(*) FROM pii_vault WHERE doc_id = %s AND position(convert_to('alice@example.invalid', 'UTF8') in encrypted_value) > 0",
        doc_id,
    )
    if vault_raw_count != "0":
        raise AssertionError("privacy vault stored raw PII without encryption")
    policy = _database_scalar(
        compose, smoke_database_url, "SELECT privacy_policy FROM document_privacy WHERE doc_id = %s", doc_id
    )
    if policy == "strict":
        chunk_raw_count = _database_scalar(
            compose,
            smoke_database_url,
            "SELECT count(*) FROM chunks WHERE doc_id = %s AND chunk_text LIKE '%%alice@example.invalid%%'",
            doc_id,
        )
        if chunk_raw_count != "0":
            raise AssertionError("STRICT mode persisted raw PII in retrieval chunks")

    if args.verify_restart:
        if smoke_database_url:
            raise RuntimeError("--verify-restart is only supported for the Compose smoke path")
        subprocess.run([*compose, "restart", "postgres"], cwd=root, check=True)
        _wait_json("http://127.0.0.1:8011/v1/readyz", timeout_seconds=90)
        persisted = _poll_document(doc_id, auth_headers)
        if ((persisted.get("job") or {}).get("status")) != "SUCCEEDED":
            raise AssertionError("required state was not preserved across database restart")

    print("SELF_HOSTED_SMOKE_OK")
    return 0


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    return _request_json(request)


def _get_text(url: str) -> str:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    merged = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=merged,
        method="POST",
    )
    return _request_json(request)


def _put_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    return _request_json(request)


def _expect_http_status(method: str, url: str, payload: dict[str, Any], expected: int) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == expected:
            return
        raise AssertionError(f"expected HTTP {expected}, got {exc.code}") from exc
    raise AssertionError(f"expected HTTP {expected}, request succeeded")


def _post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    filename: str,
    content: bytes,
    headers: dict[str, str],
) -> dict[str, Any]:
    boundary = f"----alchimista-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: text/plain\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        url,
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **headers},
        method="POST",
    )
    return _request_json(request)


def _request_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP request failed with status {exc.code}") from exc
    if not isinstance(body, dict):
        raise RuntimeError("HTTP response is not a JSON object")
    return body


def _wait_json(url: str, timeout_seconds: int = 120) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            return _get_json(url)
        except Exception:
            time.sleep(2)
    raise TimeoutError(f"service did not become ready: {url}")


def _poll_document(doc_id: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.time() + 120
    while time.time() < deadline:
        status = _get_json(f"http://127.0.0.1:8011/v1/doc/{doc_id}?tenant=default", headers)
        state = ((status.get("job") or {}).get("status") or "").upper()
        if state in {"SUCCEEDED", "FAILED"}:
            return status
        time.sleep(1)
    raise TimeoutError("document processing did not reach a terminal state")


def _compose_command() -> list[str]:
    override = os.getenv("COMPOSE_COMMAND", "").strip()
    if override:
        return override.split()
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def _psql_scalar(compose: list[str], sql: str, value: str) -> str:
    safe_value = value.replace("'", "''")
    rendered = sql % f"'{safe_value}'"
    result = subprocess.run(
        [*compose, "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "alchimista", "-tA", "-c", rendered],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _database_scalar(compose: list[str], database_url: str, sql: str, value: str) -> str:
    if not database_url:
        return _psql_scalar(compose, sql, value)
    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (value,))
            row = cursor.fetchone()
    return "" if not row else str(row[0])


def _database_execute(compose: list[str], database_url: str, sql: str, value: str) -> None:
    if not database_url:
        safe_value = value.replace("'", "''")
        rendered = sql % f"'{safe_value}'"
        subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "alchimista",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                rendered,
            ],
            check=True,
        )
        return
    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (value,))
        connection.commit()


if __name__ == "__main__":
    raise SystemExit(main())
