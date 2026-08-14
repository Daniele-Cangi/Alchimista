from __future__ import annotations

import time
from pathlib import Path

import pytest

from services.rizzo_model_service.runtime import (
    MANIFEST_NAME,
    MODEL_COMMIT,
    MODEL_DIRECTORY_NAME,
    MODEL_REVISION,
    ModelRuntime,
    ModelState,
)
from third_party.rizzo_pii.provenance import UPSTREAM_APP_VERSION


def _wait(runtime: ModelRuntime, expected: ModelState) -> dict:
    deadline = time.time() + 3
    while time.time() < deadline:
        status = runtime.status()
        if status["state"] == expected.value:
            return status
        time.sleep(0.01)
    raise AssertionError(f"runtime did not reach {expected.value}: {runtime.status()}")


def _download(**kwargs) -> None:
    assert kwargs["revision"] == MODEL_COMMIT
    target = Path(kwargs["local_dir"])
    (target / "config.json").write_text("{}", encoding="utf-8")
    (target / "model.safetensors").write_bytes(b"synthetic-weights")
    (target / "tokenizer.json").write_text("{}", encoding="utf-8")


class FakePipeline:
    def __call__(self, chunks):
        return [
            [{"entity_group": "FULLNAME", "start": 0, "end": 11, "score": 0.97}]
            for _ in chunks
        ]


def test_model_runtime_install_load_analyze_unload_and_restart(tmp_path) -> None:
    runtime = ModelRuntime(tmp_path, snapshot_download=_download, pipeline_loader=lambda path: FakePipeline())
    initial = runtime.status()
    assert initial["state"] == "NOT_INSTALLED"
    assert initial["upstream_app_version"] == UPSTREAM_APP_VERSION
    assert initial["revision"] == MODEL_REVISION
    with pytest.raises(RuntimeError, match="not loaded"):
        runtime.analyze("Mario Rossi")

    runtime.install_async()
    installed = _wait(runtime, ModelState.INSTALLED)
    assert installed["installed"] is True
    assert (runtime.target / MANIFEST_NAME).is_file()

    runtime.load_async()
    ready = _wait(runtime, ModelState.READY)
    assert ready["loaded"] is True
    result = runtime.analyze("Mario Rossi")
    assert "".join(segment["t"] for segment in result["segments"]) == "Mario Rossi"
    assert result["segments"][0]["label"] == "FULLNAME"

    unloaded = runtime.unload()
    assert unloaded["state"] == "INSTALLED"
    assert unloaded["installed"] is True
    assert unloaded["loaded"] is False

    restarted = ModelRuntime(tmp_path, snapshot_download=_download, pipeline_loader=lambda path: FakePipeline())
    assert restarted.status()["state"] == "INSTALLED"


def test_model_runtime_install_failure_is_truthful_and_retryable(tmp_path) -> None:
    attempts = 0

    def flaky(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("network unavailable")
        _download(**kwargs)

    runtime = ModelRuntime(tmp_path, snapshot_download=flaky, pipeline_loader=lambda path: FakePipeline())
    runtime.install_async()
    failed = _wait(runtime, ModelState.ERROR)
    assert failed["phase"] == "install_failed"
    assert failed["loaded"] is False

    runtime.install_async()
    assert _wait(runtime, ModelState.INSTALLED)["installed"] is True


def test_model_runtime_rejects_corrupt_persistent_installation(tmp_path) -> None:
    runtime = ModelRuntime(tmp_path, snapshot_download=_download, pipeline_loader=lambda path: FakePipeline())
    runtime.install_async()
    _wait(runtime, ModelState.INSTALLED)
    (runtime.target / "model.safetensors").write_bytes(b"corrupt")

    restarted = ModelRuntime(tmp_path)
    status = restarted.status()
    assert status["state"] == "ERROR"
    assert status["loaded"] is False


def test_model_runtime_requires_complete_artifacts(tmp_path) -> None:
    def incomplete(**kwargs):
        target = Path(kwargs["local_dir"])
        (target / "config.json").write_text("{}", encoding="utf-8")

    runtime = ModelRuntime(tmp_path, snapshot_download=incomplete)
    runtime.install_async()
    status = _wait(runtime, ModelState.ERROR)
    assert status["phase"] == "install_failed"
    assert status["installed"] is False


def test_model_runtime_cleans_orphaned_download_staging_on_bootstrap(tmp_path) -> None:
    staging = tmp_path / f".{MODEL_DIRECTORY_NAME}.partial"
    staging.mkdir()
    (staging / "incomplete.safetensors").write_bytes(b"partial")

    runtime = ModelRuntime(tmp_path, snapshot_download=_download)

    assert runtime.status()["state"] == "NOT_INSTALLED"
    assert not staging.exists()
