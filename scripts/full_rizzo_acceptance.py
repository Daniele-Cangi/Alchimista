#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from self_hosted_smoke import (
    _compose_command,
    _get_json,
    _load_env,
    _post_json,
    _post_multipart,
    _put_json,
    _wait_json,
)


MODEL_COMMIT = "a1c3c83827eca22e9675e30c1111c4641caf5901"
SOURCE_REVISION = "42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5"
MODEL_TEXT = (
    "L'avvocata Giulia Bianchi rappresenta il signor Marco Rossi. "
    "La riunione con la dottoressa Elena Verdi si svolge presso Studio Aurora."
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = _load_env(root / ".env")
    privacy_token = env.get("PRIVACY_SERVICE_TOKEN", "")
    if not privacy_token:
        raise RuntimeError("Generate .env with: python scripts/init_local_env.py")

    privacy_headers = {"x-privacy-token": privacy_token}
    compose = _compose_command()
    _wait_json("http://127.0.0.1:8000/api/v1/health", timeout_seconds=180)

    initial_model = _model(_settings())
    if initial_model.get("state") not in {"NOT_INSTALLED", "ERROR", "INSTALLED"}:
        raise AssertionError(f"unexpected initial model state: {initial_model}")

    _post_json("http://127.0.0.1:8000/api/v1/privacy/model/install", {})
    installed = _wait_model({"INSTALLED"}, timeout_seconds=1800)
    _assert_pin(installed)

    _post_json("http://127.0.0.1:8000/api/v1/privacy/model/load", {})
    ready = _wait_model({"READY"}, timeout_seconds=600)
    _assert_pin(ready)
    if not ready.get("loaded"):
        raise AssertionError("Full Rizzo reached READY without a loaded model")

    active = _put_json(
        "http://127.0.0.1:8000/api/v1/privacy/settings",
        {
            "workspace": "default",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_http",
            "privacy_mapping_enabled": True,
        },
    )
    if active.get("privacy_detector") != "rizzo_http":
        raise AssertionError("Full Rizzo did not become the active detector")

    detected = _post_json(
        "http://127.0.0.1:8014/v1/privacy/detect",
        {"text": MODEL_TEXT, "tenant": "default"},
        privacy_headers,
    )
    engine = detected.get("engine") or {}
    if engine.get("mode") != "ml_plus_regex" or engine.get("source_revision") != SOURCE_REVISION:
        raise AssertionError(f"Full detector evidence is incorrect: {engine}")
    model_findings = [item for item in detected.get("findings") or [] if item.get("detector") == "modello"]
    if not model_findings:
        raise AssertionError("Pinned Full Rizzo produced no model-origin finding for the acceptance fixture")

    upload = _post_multipart(
        "http://127.0.0.1:8000/api/v1/ingest/file",
        fields={"tenant": "default"},
        filename="full-rizzo-acceptance.txt",
        content=(MODEL_TEXT + " La clausola di conservazione è di quarantacinque giorni.").encode("utf-8"),
        headers={},
    )
    uploaded_id = str(upload.get("doc_id") or "")
    if not uploaded_id:
        raise AssertionError(f"product upload did not return a document id: {upload}")
    detail = _wait_document(uploaded_id)
    if detail.get("privacy_detector") != "ml_plus_regex":
        raise AssertionError(f"document did not retain Full detector evidence: {detail}")
    if detail.get("privacy_engine_version") != "model-v1.5.0":
        raise AssertionError("document did not retain the Full detector version")
    if detail.get("privacy_engine_source_revision") != SOURCE_REVISION:
        raise AssertionError("document did not retain the Full detector source revision")

    answer = _post_json(
        "http://127.0.0.1:8000/api/v1/query",
        {
            "tenant": "default",
            "query": "Qual è il periodo di conservazione?",
            "k": 3,
            "doc_ids": [uploaded_id],
        },
    )
    citations = answer.get("citations") or []
    if not answer.get("answer") or not citations:
        raise AssertionError("Full-model document did not produce an answer with evidence")
    decision_id = str(answer.get("trace_id") or f"full-rizzo-decision-{uuid.uuid4().hex[:12]}")
    _post_json(
        "http://127.0.0.1:8000/api/v1/decisions",
        {
            "tenant": "default",
            "trace_id": decision_id,
            "decision_type": "rag_answer",
            "citations": citations,
            "context": {
                "query": "Qual è il periodo di conservazione?",
                "answer": answer["answer"],
                "confidence": answer.get("score"),
                "model": "alchimista-rag",
                "model_version": "local",
            },
            "metadata": {"source": "full-rizzo-acceptance"},
        },
    )
    report = _get_json(
        f"http://127.0.0.1:8000/api/v1/decisions/report?tenant=default&decision_id={decision_id}"
    )
    evidence = ((report.get("decision") or {}).get("metadata") or {}).get("privacy") or {}
    if evidence.get("decision_privacy_detector") != "ml_plus_regex":
        raise AssertionError(f"audit evidence did not retain Full detector metadata: {evidence}")

    subprocess.run([*compose, "restart", "rizzo-model-service", "privacy-service"], cwd=root, check=True)
    _wait_json("http://127.0.0.1:8014/v1/privacy/ready", timeout_seconds=180)
    after_restart = _model(_settings())
    if after_restart.get("state") != "INSTALLED" or not after_restart.get("installed"):
        raise AssertionError(f"model weights did not persist across restart: {after_restart}")
    _assert_pin(after_restart)

    _post_json("http://127.0.0.1:8000/api/v1/privacy/model/load", {})
    _wait_model({"READY"}, timeout_seconds=600)
    _put_json(
        "http://127.0.0.1:8000/api/v1/privacy/settings",
        {
            "workspace": "default",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_regex",
            "privacy_mapping_enabled": True,
        },
    )
    unloaded = _post_json("http://127.0.0.1:8000/api/v1/privacy/model/unload", {})
    if unloaded.get("state") != "INSTALLED" or unloaded.get("loaded"):
        raise AssertionError(f"unload did not retain installed weights: {unloaded}")
    _post_json("http://127.0.0.1:8000/api/v1/privacy/model/load", {})
    _wait_model({"READY"}, timeout_seconds=600)
    final = _post_json("http://127.0.0.1:8000/api/v1/privacy/model/unload", {})
    if final.get("state") != "INSTALLED":
        raise AssertionError("Full Rizzo could not be loaded again without reinstalling")

    print(
        "FULL_RIZZO_ACCEPTANCE_OK "
        + json.dumps(
            {
                "document_id": uploaded_id,
                "decision_id": decision_id,
                "model_commit": MODEL_COMMIT,
                "source_revision": SOURCE_REVISION,
                "model_finding_types": sorted({str(item.get('type')) for item in model_findings}),
            },
            sort_keys=True,
        )
    )
    return 0


def _settings() -> dict[str, Any]:
    return _get_json("http://127.0.0.1:8000/api/v1/privacy/settings?workspace=default")


def _model(settings: dict[str, Any]) -> dict[str, Any]:
    model = settings.get("model") or {}
    if not isinstance(model, dict):
        raise AssertionError(f"invalid model status: {settings}")
    return model


def _assert_pin(model: dict[str, Any]) -> None:
    if model.get("model_commit") != MODEL_COMMIT or model.get("source_revision") != SOURCE_REVISION:
        raise AssertionError(f"runtime pin mismatch: {model}")


def _wait_model(expected: set[str], *, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _model(_settings())
        state = str(last.get("state") or "")
        if state in expected:
            return last
        if state == "ERROR":
            raise AssertionError(f"Full Rizzo entered ERROR: {last}")
        time.sleep(5)
    raise TimeoutError(f"timed out waiting for model state {sorted(expected)}; last={last}")


def _wait_document(doc_id: str, *, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = _get_json(f"http://127.0.0.1:8000/api/v1/doc/{doc_id}?tenant=default")
        current = str(status.get("status") or "")
        if current == "FAILED":
            raise AssertionError(f"Full-model document processing failed: {status}")
        if current == "SUCCEEDED":
            last = _get_json(f"http://127.0.0.1:8000/api/v1/documents/{doc_id}?workspace=default")
            if last.get("evidence"):
                return last
        time.sleep(2)
    raise TimeoutError(f"timed out waiting for Full-model document; last={last}")


if __name__ == "__main__":
    raise SystemExit(main())
