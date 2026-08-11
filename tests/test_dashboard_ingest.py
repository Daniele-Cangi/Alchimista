from __future__ import annotations

import json
from importlib import import_module

import requests
from fastapi.testclient import TestClient

dashboard = import_module("services.dashboard_service.app")


def test_dashboard_forwards_local_file_as_multipart(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, data, files, headers, timeout):
        captured.update(
            url=url,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout,
        )
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"doc_id": "doc-local", "status": "QUEUED", "published": True}
        ).encode("utf-8")
        response.headers["Content-Type"] = "application/json"
        return response

    monkeypatch.setattr(dashboard.requests, "post", fake_post)

    response = TestClient(dashboard.app).post(
        "/api/v1/ingest/file",
        data={"tenant": "tenant-a"},
        files={"file": ("notes.txt", b"private text", "text/plain")},
        headers={"Authorization": "Bearer local-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["doc_id"] == "doc-local"
    assert captured["url"] == f"{dashboard.INGEST_URL}/v1/ingest"
    assert captured["data"] == {"tenant": "tenant-a"}
    assert captured["headers"] == {"Authorization": "Bearer local-test-token"}
    assert captured["timeout"] == 120
    assert captured["files"] == {
        "file": ("notes.txt", b"private text", "text/plain")
    }
