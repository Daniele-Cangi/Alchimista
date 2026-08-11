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
    assert "Alchimista" in response.text
    assert "Home" in response.text
    assert "Documenti" in response.text
    assert "Bearer Token" not in response.text
    assert "Auth0" not in response.text

    script = (Path(dashboard.__file__).parent / "static" / "js" / "product.js").read_text(encoding="utf-8")
    assert "Bearer Token" not in script
    assert "AUTH0" not in script


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
