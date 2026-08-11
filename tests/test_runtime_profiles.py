import pytest

from services.shared.config import load_runtime_config


def _clear_profile_env(monkeypatch) -> None:
    for name in (
        "ALCHIMISTA_PROFILE",
        "ALCHIMISTA_ENV",
        "ENVIRONMENT",
        "PROJECT_ID",
        "STORAGE_BACKEND",
        "QUEUE_BACKEND",
        "AUTH_MODE",
        "AUTH_ENABLED",
        "LOCAL_AUTH_TOKEN",
        "ALCHIMISTA_API_TOKEN",
        "PRIVACY_POLICY",
        "PRIVACY_SERVICE_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_local_profile_requires_no_cloud_configuration(monkeypatch) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)

    config = load_runtime_config()

    assert config.profile == "local"
    assert config.project_id == ""
    assert config.storage_backend == "filesystem"
    assert config.queue_backend == "direct_http"
    assert config.auth_mode == "local"


def test_gcp_profile_requires_project_id(monkeypatch) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("ALCHIMISTA_PROFILE", "gcp")

    with pytest.raises(RuntimeError, match="PROJECT_ID"):
        load_runtime_config()


def test_disabled_auth_fails_closed_in_production(monkeypatch) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("ALCHIMISTA_ENV", "production")

    with pytest.raises(RuntimeError, match="not allowed"):
        load_runtime_config()
