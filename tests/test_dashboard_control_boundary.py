from __future__ import annotations

import json
from importlib import import_module

import requests
from fastapi.testclient import TestClient

dashboard = import_module("services.dashboard_service.app")


def _response(payload: dict) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def test_privileged_mutation_requires_control_header(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("blocked requests must not reach the privileged proxy")
        ),
    )

    response = TestClient(dashboard.app).post("/api/v1/privacy/model/install")

    assert response.status_code == 403
    assert response.json()["detail"] == "Same-origin control header required"


def test_control_header_does_not_override_cross_site_browser_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cross-site requests must not reach the privileged proxy")
        ),
    )
    response = TestClient(dashboard.app).post(
        "/api/v1/admin/retention/enforce",
        headers={
            "X-Alchimista-Control": "same-origin",
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
        json={"tenant": "default", "dry_run": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site control request rejected"


def test_unlisted_origin_is_rejected_even_with_control_header(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unlisted origins must not reach the privileged proxy")
        ),
    )
    response = TestClient(dashboard.app).post(
        "/api/v1/privacy/model/load",
        headers={
            "X-Alchimista-Control": "same-origin",
            "Origin": "https://attacker.example",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Request origin is not allowed"


def test_same_origin_model_action_reaches_privileged_proxy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return _response({"state": "DOWNLOADING"})

    monkeypatch.setattr(dashboard, "PRIVACY_SERVICE_TOKEN", "privacy-internal-token")
    monkeypatch.setattr(dashboard.requests, "post", fake_post)
    response = TestClient(dashboard.app).post(
        "/api/v1/privacy/model/install",
        headers={
            "X-Alchimista-Control": "same-origin",
            "Origin": "http://127.0.0.1:8000",
            "Sec-Fetch-Site": "same-origin",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "DOWNLOADING"
    assert captured["url"] == f"{dashboard.PRIVACY_URL}/v1/privacy/model/install"
    assert "X-Alchimista-Control" not in captured["headers"]


def test_non_browser_automation_may_use_control_header_without_origin(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "PRIVACY_SERVICE_TOKEN", "privacy-internal-token")
    monkeypatch.setattr(
        dashboard.requests,
        "post",
        lambda url, *, headers, timeout: _response({"state": "INSTALLED"}),
    )

    response = TestClient(dashboard.app).post(
        "/api/v1/privacy/model/unload",
        headers={"X-Alchimista-Control": "same-origin"},
    )

    assert response.status_code == 200


def test_cross_origin_preflight_is_not_granted() -> None:
    response = TestClient(dashboard.app).options(
        "/api/v1/privacy/model/install",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Alchimista-Control",
        },
    )

    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers
