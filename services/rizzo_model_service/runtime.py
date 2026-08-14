from __future__ import annotations

import gc
import bisect
import hashlib
import json
import os
import shutil
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from third_party.rizzo_pii.detectors import SOFT_REGEX_LABELS, detect_regex
from third_party.rizzo_pii.provenance import (
    MODEL_COMMIT,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    UPSTREAM_APP_VERSION,
    UPSTREAM_SOURCE_REVISION,
)


SOURCE_REVISION = UPSTREAM_SOURCE_REVISION
MODEL_DIRECTORY_NAME = "rizzo-pii-0.3B-v1.5.0"
MANIFEST_NAME = "alchimista-manifest.json"
ALLOWED_PATTERNS = ("*.json", "*.safetensors", "*.txt", "*.model")


class ModelState(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    DOWNLOADING = "DOWNLOADING"
    INSTALLED = "INSTALLED"
    LOADING = "LOADING"
    READY = "READY"
    ERROR = "ERROR"


class ModelRuntime:
    def __init__(
        self,
        model_root: str | Path,
        *,
        snapshot_download: Callable[..., Any] | None = None,
        pipeline_loader: Callable[[Path], Any] | None = None,
    ) -> None:
        self.root = Path(model_root).resolve()
        self.target = self.root / MODEL_DIRECTORY_NAME
        self.staging = self.root / f".{MODEL_DIRECTORY_NAME}.partial"
        self._snapshot_download = snapshot_download or _download_snapshot
        self._pipeline_loader = pipeline_loader or _load_pipeline
        self._lock = threading.RLock()
        self._pipeline: Any | None = None
        self._state = ModelState.NOT_INSTALLED
        self._phase = "not_installed"
        self._error: str | None = None
        self.root.mkdir(parents=True, exist_ok=True)
        self._inspect_disk()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "phase": self._phase,
                "error": self._error,
                "repository": MODEL_REPOSITORY,
                "revision": MODEL_REVISION,
                "model_commit": MODEL_COMMIT,
                "upstream_app_version": UPSTREAM_APP_VERSION,
                "source_revision": SOURCE_REVISION,
                "installed": self._state in {ModelState.INSTALLED, ModelState.LOADING, ModelState.READY},
                "loaded": self._state == ModelState.READY and self._pipeline is not None,
            }

    def install_async(self) -> dict[str, Any]:
        with self._lock:
            if self._state in {ModelState.DOWNLOADING, ModelState.LOADING, ModelState.READY}:
                return self.status()
            if self._state == ModelState.INSTALLED:
                return self.status()
            self._state = ModelState.DOWNLOADING
            self._phase = "preparing_download"
            self._error = None
            threading.Thread(target=self._install, name="rizzo-install", daemon=True).start()
            return self.status()

    def load_async(self) -> dict[str, Any]:
        with self._lock:
            if self._state in {ModelState.LOADING, ModelState.READY}:
                return self.status()
            if self._state != ModelState.INSTALLED:
                raise RuntimeError("Rizzo model must be installed before it can be loaded")
            self._state = ModelState.LOADING
            self._phase = "loading_model"
            self._error = None
            threading.Thread(target=self._load, name="rizzo-load", daemon=True).start()
            return self.status()

    def unload(self) -> dict[str, Any]:
        with self._lock:
            if self._state in {ModelState.DOWNLOADING, ModelState.LOADING}:
                raise RuntimeError("Rizzo model is busy")
            self._pipeline = None
            if self._validate_installation():
                self._state = ModelState.INSTALLED
                self._phase = "installed"
                self._error = None
            else:
                self._state = ModelState.ERROR
                self._phase = "validation_failed"
                self._error = "Installed model files failed manifest validation"
        gc.collect()
        _empty_accelerator_cache()
        return self.status()

    def analyze(self, text: str) -> dict[str, Any]:
        with self._lock:
            pipeline = self._pipeline
            if self._state != ModelState.READY or pipeline is None:
                raise RuntimeError("Rizzo model is not loaded")
        model_candidates = _detect_model(pipeline, text)
        candidates = _merge_candidates([*model_candidates, *detect_regex(text)])
        return {"segments": _segments(text, candidates), "model_revision": MODEL_REVISION}

    def _inspect_disk(self) -> None:
        if self.staging.exists() or self.staging.is_symlink():
            try:
                self._remove_staging()
            except OSError as exc:
                self._state = ModelState.ERROR
                self._phase = "staging_cleanup_failed"
                self._error = f"Could not remove incomplete model staging: {_safe_error(exc)}"
                return
        if self._validate_installation():
            self._state = ModelState.INSTALLED
            self._phase = "installed"
            return
        if self.target.exists():
            self._state = ModelState.ERROR
            self._phase = "validation_failed"
            self._error = "Incomplete or corrupt model installation; retry install to repair it"

    def _install(self) -> None:
        try:
            self._remove_staging()
            if self.target.exists():
                shutil.rmtree(self.target)
            self.staging.mkdir(parents=True, exist_ok=False)
            with self._lock:
                self._phase = "downloading_model_files"
            self._snapshot_download(
                repo_id=MODEL_REPOSITORY,
                revision=MODEL_COMMIT,
                local_dir=str(self.staging),
                allow_patterns=list(ALLOWED_PATTERNS),
            )
            with self._lock:
                self._phase = "verifying_model_files"
            manifest = _build_manifest(self.staging)
            _validate_required_files(self.staging, manifest)
            (self.staging / MANIFEST_NAME).write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(self.staging, self.target)
            with self._lock:
                self._state = ModelState.INSTALLED
                self._phase = "installed"
                self._error = None
        except Exception as exc:
            self._remove_staging()
            with self._lock:
                self._state = ModelState.ERROR
                self._phase = "install_failed"
                self._error = _safe_error(exc)

    def _load(self) -> None:
        try:
            if not self._validate_installation():
                raise RuntimeError("Installed model files failed manifest validation")
            loaded = self._pipeline_loader(self.target)
            with self._lock:
                self._pipeline = loaded
                self._state = ModelState.READY
                self._phase = "ready"
                self._error = None
        except Exception as exc:
            with self._lock:
                self._pipeline = None
                self._state = ModelState.ERROR
                self._phase = "load_failed"
                self._error = _safe_error(exc)

    def _validate_installation(self) -> bool:
        manifest_path = self.target / MANIFEST_NAME
        if not manifest_path.is_file():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            _validate_required_files(self.target, manifest)
            for relative, expected in files.items():
                path = self.target / relative
                if not path.is_file() or _sha256(path) != expected:
                    return False
            return (
                manifest.get("repository") == MODEL_REPOSITORY
                and manifest.get("revision") == MODEL_REVISION
                and manifest.get("model_commit") == MODEL_COMMIT
            )
        except Exception:
            return False

    def _remove_staging(self) -> None:
        if self.staging.parent != self.root:
            raise RuntimeError("Unsafe model staging path")
        if self.staging.is_symlink() or self.staging.is_file():
            self.staging.unlink()
        elif self.staging.exists():
            shutil.rmtree(self.staging)


def _download_snapshot(**kwargs: Any) -> Any:
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


def _load_pipeline(model_path: Path) -> Any:
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    return pipeline(
        "token-classification",
        model=str(model_path),
        tokenizer=str(model_path),
        aggregation_strategy="simple",
        device=device,
    )


def _empty_accelerator_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _build_manifest(directory: Path) -> dict[str, Any]:
    root = directory.resolve()
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            raise RuntimeError("Downloaded model contains a file outside its installation directory")
        files[path.relative_to(directory).as_posix()] = _sha256(path)
    return {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "model_commit": MODEL_COMMIT,
        "source_revision": SOURCE_REVISION,
        "files": files,
    }


def _validate_required_files(directory: Path, manifest: dict[str, Any]) -> None:
    files = set(manifest.get("files") or {})
    if "config.json" not in files:
        raise RuntimeError("Downloaded model is missing config.json")
    if not any(name.endswith(".safetensors") for name in files):
        raise RuntimeError("Downloaded model is missing safetensors weights")
    if not any(name.startswith("tokenizer") or name.endswith(".model") for name in files):
        raise RuntimeError("Downloaded model is missing tokenizer files")
    for relative in files:
        path = (directory / relative).resolve()
        if directory.resolve() not in path.parents:
            raise RuntimeError("Model manifest contains an unsafe path")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _detect_model(pipeline: Any, text: str) -> list[dict[str, Any]]:
    words = list(__import__("re").finditer(r"\S+", text))
    chunks: list[tuple[str, int]] = []
    index = 0
    while index < len(words):
        block = words[index : index + 120]
        if not block:
            break
        start, end = block[0].start(), block[-1].end()
        chunks.append((text[start:end], start))
        if index + 120 >= len(words):
            break
        index += 100
    if not chunks:
        return []
    output = pipeline([item[0] for item in chunks])
    if output and isinstance(output[0], dict):
        output = [output]
    entities: list[dict[str, Any]] = []
    for (_, offset), chunk_entities in zip(chunks, output):
        for entity in chunk_entities:
            entities.append(
                {
                    "label": str(entity["entity_group"]),
                    "start": int(entity["start"]) + offset,
                    "end": int(entity["end"]) + offset,
                    "score": float(entity["score"]),
                    "validated": False,
                    "source": "modello",
                }
            )
    return entities


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            1 if item.get("validated") else 0,
            1 if item.get("source") == "regex" and item.get("label") not in SOFT_REGEX_LABELS else 0,
            float(item.get("score") or 0.0),
            int(item["end"]) - int(item["start"]),
        ),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    for item in ordered:
        index = bisect.bisect_right(kept, int(item["start"]), key=lambda value: int(value["start"]))
        overlaps_left = index and int(kept[index - 1]["end"]) > int(item["start"])
        overlaps_right = index < len(kept) and int(kept[index]["start"]) < int(item["end"])
        if not overlaps_left and not overlaps_right:
            kept.insert(index, dict(item))
    return kept


def _segments(text: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = 0
    for candidate in candidates:
        start, end = int(candidate["start"]), int(candidate["end"])
        if start > cursor:
            segments.append({"t": text[cursor:start]})
        segments.append(
            {
                "t": text[start:end],
                "label": str(candidate["label"]),
                "validated": bool(candidate.get("validated")),
                "src": str(candidate.get("source") or "modello"),
                "score": float(candidate.get("score") or 0.0),
            }
        )
        cursor = end
    if cursor < len(text):
        segments.append({"t": text[cursor:]})
    return segments


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip()
    return (message[:300] if message else exc.__class__.__name__)
