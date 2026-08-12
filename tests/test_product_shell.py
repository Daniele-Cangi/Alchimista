from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import requests
from fastapi.testclient import TestClient

dashboard = import_module("services.dashboard_service.app")


def _response(payload: dict, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def test_localhost_root_is_product_shell_without_auth_fields() -> None:
    response = TestClient(dashboard.app).get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "Alchimista" in response.text
    assert "Home" in response.text
    assert "Documenti" in response.text
    assert "/static/images/logo/logo-dark.png" in response.text
    assert "Governance locale" in response.text
    assert "Bearer Token" not in response.text
    assert "Auth0" not in response.text

    script = (Path(dashboard.__file__).parent / "static" / "js" / "product.js").read_text(encoding="utf-8")
    stylesheet = (Path(dashboard.__file__).parent / "static" / "css" / "product.css").read_text(encoding="utf-8")
    assert "Bearer Token" not in script
    assert "AUTH0" not in script
    assert 'request.headers.set("X-Alchimista-Control", "same-origin")' in script
    assert "Rimozione governata" in script
    assert "#document-delete-modal" in script
    assert 'data-delete-doc="${esc(d.doc_id)}"' in script
    assert "<th>Azioni</th>" in script
    assert "if (event.target.closest(\"[data-delete-doc]\")) return" in script
    assert ".dropzone {" in stylesheet
    assert "width: 100%;" in stylesheet
    assert "display: flex;" in stylesheet


def test_document_proxy_propagates_workspace_and_uses_server_token(monkeypatch) -> None:
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return _response({"workspace": "matter-a", "documents": [], "total": 0})

    monkeypatch.setattr(dashboard, "DASHBOARD_API_TOKEN", "server-side-only")
    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    response = TestClient(dashboard.app).get("/api/v1/documents?workspace=matter-a")

    assert response.status_code == 200
    assert captured["params"]["tenant"] == "matter-a"
    assert captured["headers"] == {"Authorization": "Bearer server-side-only"}


def test_document_delete_proxy_preserves_governance_payload(monkeypatch) -> None:
    captured = {}

    def fake_delete(url, *, json, params, headers, timeout):
        captured.update(url=url, json=json, params=params, headers=headers, timeout=timeout)
        return _response(
            {
                "tenant": "matter-a",
                "doc_id": "doc-1",
                "deleted": True,
                "already_deleted": False,
                "storage_deleted": True,
                "tombstone_id": "del-1",
                "deleted_at": "2026-08-12T10:00:00Z",
            }
        )

    monkeypatch.setattr(dashboard, "DASHBOARD_API_TOKEN", "server-side-only")
    monkeypatch.setattr(dashboard.requests, "delete", fake_delete)
    response = TestClient(dashboard.app).request(
        "DELETE",
        "/api/v1/documents/doc-1?workspace=matter-a",
        headers={"X-Alchimista-Control": "same-origin"},
        json={"confirmation": "report.pdf", "reason": "User requested removal"},
    )

    assert response.status_code == 200
    assert captured["params"] == {"tenant": "matter-a"}
    assert captured["json"]["confirmation"] == "report.pdf"
    assert captured["headers"] == {"Authorization": "Bearer server-side-only"}


def test_health_summary_includes_privacy(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        if url.endswith("/v1/privacy/health"):
            return _response({"status": "ok", "privacy_policy": "strict", "privacy_detector": "rizzo_regex", "detector_ready": True})
        return _response({"status": "ok"})

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    response = TestClient(dashboard.app).get("/api/v1/health")
    body = response.json()

    assert response.status_code == 200
    assert body["services"]["privacy"]["status"] == "healthy"
    assert body["services"]["privacy"]["policy"] == "strict"


def test_vercel_git_deployments_are_explicitly_disabled() -> None:
    config = json.loads((Path(__file__).parents[1] / "vercel.json").read_text(encoding="utf-8"))

    assert config["git"]["deploymentEnabled"] is False
    assert "builds" not in config
    assert "routes" not in config
