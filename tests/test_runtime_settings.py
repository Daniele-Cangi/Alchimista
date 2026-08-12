from __future__ import annotations

from contextlib import contextmanager

import pytest

from services.shared import runtime_settings as module
from services.shared.runtime_settings import RuntimeSettingsStore


class FakeCursor:
    def __init__(self, rows, history, queries):
        self.rows = rows
        self.history = history
        self.queries = queries
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        normalized = " ".join(query.split())
        self.queries.append(normalized)
        if normalized.startswith("SELECT workspace"):
            self.result = self.rows.get(params[0])
        elif "INSERT INTO runtime_settings_history" in normalized:
            self.history.append(params)
            self.result = None
        elif "INSERT INTO runtime_settings" in normalized:
            workspace, policy, detector, mapping = params[:4]
            row = {
                "workspace": workspace,
                "privacy_policy": policy,
                "privacy_detector": detector,
                "privacy_mapping_enabled": mapping,
            }
            if "DO NOTHING" in normalized:
                if workspace in self.rows:
                    self.result = None
                else:
                    self.rows[workspace] = row
                    self.result = row
            else:
                self.rows[workspace] = row
                self.result = None
        else:
            raise AssertionError(normalized)

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, rows, history):
        self.rows = rows
        self.history = history
        self.queries = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.rows, self.history, self.queries)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_runtime_settings_persist_policy_detector_and_mapping(monkeypatch) -> None:
    rows, history = {}, []

    @contextmanager
    def fake_connection(database_url):
        assert database_url == "postgresql://settings"
        yield FakeConnection(rows, history)

    monkeypatch.setattr(module, "get_connection", fake_connection)
    store = RuntimeSettingsStore(
        "postgresql://settings",
        default_policy="protect_egress",
        default_detector="rizzo_regex",
        default_mapping_enabled=True,
    )

    assert store.get("matter-a").privacy_policy == "protect_egress"
    updated = store.update(
        workspace="matter-a",
        privacy_policy="strict",
        privacy_detector="rizzo_http",
        privacy_mapping_enabled=False,
        changed_by="test",
    )
    assert updated.privacy_policy == "strict"
    assert store.get("matter-a") == updated
    assert history[-1] == ("matter-a", "strict", "rizzo_http", False, "test")


def test_processing_snapshot_holds_transaction_until_operation_finishes(monkeypatch) -> None:
    rows = {
        "matter-a": {
            "workspace": "matter-a",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_http",
            "privacy_mapping_enabled": False,
        }
    }
    history, connections = [], []

    @contextmanager
    def fake_connection(database_url):
        assert database_url == "postgresql://settings"
        connection = FakeConnection(rows, history)
        connections.append(connection)
        yield connection

    monkeypatch.setattr(module, "get_connection", fake_connection)
    store = RuntimeSettingsStore(
        "postgresql://settings",
        default_policy="off",
        default_detector="rizzo_regex",
        default_mapping_enabled=True,
    )

    with store.processing_snapshot("matter-a") as selected:
        assert selected.privacy_policy == "strict"
        assert selected.privacy_detector == "rizzo_http"
        assert connections[-1].commits == 0

    assert connections[-1].commits == 1
    assert connections[-1].rollbacks == 0
    assert any(query.endswith("FOR SHARE") for query in connections[-1].queries)


@pytest.mark.parametrize("field,value", [("privacy_policy", "unknown"), ("privacy_detector", "fallback")])
def test_runtime_settings_reject_unknown_values(field, value) -> None:
    kwargs = {
        "default_policy": "protect_egress",
        "default_detector": "rizzo_regex",
        "default_mapping_enabled": True,
    }
    kwargs["default_policy" if field == "privacy_policy" else "default_detector"] = value
    with pytest.raises(ValueError):
        RuntimeSettingsStore("postgresql://unused", **kwargs)
