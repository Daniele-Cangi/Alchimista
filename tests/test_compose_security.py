from __future__ import annotations

import re
from pathlib import Path


COMPOSE_PATH = Path(__file__).parents[1] / "compose.yaml"
VAULT_KEY_ENV = (
    "PRIVACY_VAULT_ACTIVE_KEY_VERSION",
    "PRIVACY_VAULT_KEYS_JSON",
    "PRIVACY_VAULT_KEY",
    "PRIVACY_VAULT_KEY_VERSION",
)


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _service_block(text: str, service: str) -> str:
    marker = f"  {service}:\n"
    remainder = text.split(marker, 1)[1]
    next_service = re.search(r"^  [a-z0-9-]+:\s*$", remainder, re.MULTILINE)
    return remainder[: next_service.start()] if next_service else remainder


def test_vault_keys_are_available_only_to_privacy_service() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    common_environment = _between(
        compose,
        "x-common-runtime-environment: &common-runtime-environment\n",
        "x-privacy-runtime-environment: &privacy-runtime-environment\n",
    )
    privacy_environment = _between(
        compose,
        "x-privacy-runtime-environment: &privacy-runtime-environment\n",
        "services:\n",
    )

    assert "environment: *privacy-runtime-environment" in _service_block(
        compose, "privacy-service"
    )
    for variable in VAULT_KEY_ENV:
        assert variable not in common_environment
        assert variable in privacy_environment

    for service in (
        "document-processor-service",
        "ingestion-api-service",
        "rag-query-service",
    ):
        block = _service_block(compose, service)
        assert "environment: *common-runtime-environment" in block
        assert all(variable not in block for variable in VAULT_KEY_ENV)


def test_model_control_secret_is_limited_to_privacy_and_model_services() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "/var/run/docker.sock" not in compose
    assert "ports:" not in _service_block(compose, "rizzo-model-service")
    assert "RIZZO_MODEL_TOKEN" in _service_block(compose, "rizzo-model-service")
    privacy_environment = _between(
        compose,
        "x-privacy-runtime-environment: &privacy-runtime-environment\n",
        "services:\n",
    )
    assert "RIZZO_MODEL_TOKEN" in privacy_environment
    assert "environment: *privacy-runtime-environment" in _service_block(compose, "privacy-service")
    for service in ("document-processor-service", "ingestion-api-service", "rag-query-service", "dashboard-service"):
        assert "RIZZO_MODEL_TOKEN" not in _service_block(compose, service)

    for service in ("postgres", "schema-init", "dashboard-service"):
        block = _service_block(compose, service)
        assert all(variable not in block for variable in VAULT_KEY_ENV)
