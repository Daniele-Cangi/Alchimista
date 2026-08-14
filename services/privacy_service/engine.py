from __future__ import annotations

import bisect
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.privacy_service.vault import PiiVaultRepository, VaultCipher
from services.shared.privacy import PrivacyEngineMetadata, PrivacyFinding
from third_party.rizzo_pii.detectors import SOFT_REGEX_LABELS, detect_regex
from third_party.rizzo_pii.provenance import (
    MODEL_REVISION,
    REGEX_ENGINE_VERSION,
    UPSTREAM_SOURCE_REVISION,
)


RIZZO_SOURCE_REVISION = UPSTREAM_SOURCE_REVISION
RIZZO_ENGINE_VERSION = REGEX_ENGINE_VERSION
RIZZO_HTTP_MAX_REQUEST_CHARS = 1_000_000
RIZZO_HTTP_OVERLAP_CHARS = 4_096


class Detector(Protocol):
    metadata: PrivacyEngineMetadata
    def detect(self, text: str) -> list[dict[str, Any]]: ...
    def ready(self) -> bool: ...


class RizzoRegexDetector:
    metadata = PrivacyEngineMetadata(
        name="rizzo-pii",
        version=RIZZO_ENGINE_VERSION,
        source_revision=RIZZO_SOURCE_REVISION,
        mode="regex_checksum",
    )

    def detect(self, text: str) -> list[dict[str, Any]]:
        return _merge_candidates(detect_regex(text))

    def ready(self) -> bool:
        return True


class RizzoHttpDetector:
    """Optional adapter for the full upstream Rizzo CPU/ML service."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 120,
        token: str = "",
        *,
        max_request_chars: int = RIZZO_HTTP_MAX_REQUEST_CHARS,
        overlap_chars: int = RIZZO_HTTP_OVERLAP_CHARS,
    ):
        if max_request_chars <= 0:
            raise ValueError("max_request_chars must be positive")
        if overlap_chars < 0 or overlap_chars >= max_request_chars:
            raise ValueError("overlap_chars must be non-negative and smaller than max_request_chars")
        base = base_url.rstrip("/")
        self._url = base + "/analyze"
        self._health_url = base + "/health"
        self._timeout_seconds = timeout_seconds
        self._token = token
        self._max_request_chars = max_request_chars
        self._overlap_chars = overlap_chars
        self.metadata = PrivacyEngineMetadata(
            name="rizzo-pii",
            version=f"model-{MODEL_REVISION}",
            source_revision=RIZZO_SOURCE_REVISION,
            mode="ml_plus_regex",
        )

    def ready(self) -> bool:
        try:
            request = Request(
                self._health_url,
                headers={"x-model-token": self._token} if self._token else {},
                method="GET",
            )
            with urlopen(request, timeout=min(10, self._timeout_seconds)) as response:
                return response.status == 200
        except Exception:
            return False

    def detect(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        candidates: list[dict[str, Any]] = []
        for window, base_offset in _text_windows(
            text,
            max_chars=self._max_request_chars,
            overlap_chars=self._overlap_chars,
        ):
            candidates.extend(self._detect_window(window, base_offset, len(text)))
        return _merge_candidates(candidates)

    def _detect_window(
        self,
        text: str,
        base_offset: int,
        total_chars: int,
    ) -> list[dict[str, Any]]:
        request = Request(
            self._url,
            data=json.dumps({"text": text, "include_mapping": True}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"x-model-token": self._token} if self._token else {}),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("Rizzo ML detector is unavailable") from exc
        try:
            body = json.loads(raw_body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Rizzo ML detector returned a malformed response") from exc
        segments = body.get("segments") if isinstance(body, dict) else None
        if not isinstance(segments, list):
            raise RuntimeError("Rizzo ML detector returned a malformed response")
        candidates: list[dict[str, Any]] = []
        offset = 0
        for segment in segments:
            if not isinstance(segment, dict):
                raise RuntimeError("Rizzo ML detector returned a malformed segment")
            value = str(segment.get("t") or "")
            label = segment.get("label")
            if label and value:
                touches_internal_left = base_offset > 0 and offset == 0
                touches_internal_right = (
                    base_offset + len(text) < total_chars
                    and offset + len(value) == len(text)
                )
                if not touches_internal_left and not touches_internal_right:
                    candidates.append(
                        {
                            "label": str(label),
                            "start": base_offset + offset,
                            "end": base_offset + offset + len(value),
                            "score": float(
                                segment.get("score")
                                or (1.0 if segment.get("validated") else 0.9)
                            ),
                            "validated": bool(segment.get("validated")),
                            "source": str(segment.get("src") or "modello"),
                        }
                    )
            offset += len(value)
        if offset != len(text):
            raise RuntimeError("Rizzo ML detector response offsets do not match input")
        return candidates


@dataclass(frozen=True)
class ProtectionResult:
    protected_text: str
    findings: list[PrivacyFinding]
    raw_mappings: list[tuple[str, str, str, str]]


class PrivacyEngine:
    def __init__(self, *, detector: Detector, cipher: VaultCipher, vault: PiiVaultRepository | None):
        self.detector = detector
        self.cipher = cipher
        self.vault = vault

    def protect(
        self,
        *,
        text: str,
        tenant: str,
        doc_id: str | None,
        replace: bool,
        reversible: bool,
        persist_mapping: bool,
    ) -> ProtectionResult:
        if reversible and persist_mapping and (not doc_id or self.vault is None):
            raise ValueError("Reversible pseudonymization requires doc_id and an available vault")
        existing: dict[tuple[str, str], str] = {}
        if reversible and persist_mapping and self.vault and doc_id:
            self.vault.assert_document_scope(tenant=tenant, doc_id=doc_id)
            existing = self.vault.load_value_placeholders(tenant=tenant, doc_id=doc_id)

        entities = self.detector.detect(text)
        reserved = set(re.findall(r"\[[A-Z][A-Z0-9_]*_\d+\]", text))
        counters: dict[str, int] = {}
        seen: dict[tuple[str, str], str] = {}
        findings: list[PrivacyFinding] = []
        raw_mappings: list[tuple[str, str, str, str]] = []

        for entity in entities:
            start, end = int(entity["start"]), int(entity["end"])
            raw_value = text[start:end]
            entity_type = str(entity["label"]).upper()
            key = (entity_type, _normalize(raw_value))
            placeholder = seen.get(key)
            if placeholder is None:
                candidate = existing.get(key)
                if candidate and candidate not in reserved:
                    placeholder = candidate
                else:
                    placeholder = _next_placeholder(entity_type, counters, reserved)
                seen[key] = placeholder
                reserved.add(placeholder)
            value_hash = self.cipher.value_hash(raw_value)
            finding = PrivacyFinding(
                type=entity_type,
                detector=str(entity.get("source") or self.detector.metadata.mode),
                confidence=float(entity.get("score") or 0.0),
                start=start,
                end=end,
                placeholder=placeholder,
                value_hash=value_hash,
                validated=bool(entity.get("validated")),
                metadata={"engine_mode": self.detector.metadata.mode},
            )
            findings.append(finding)
            if key not in {(item[0], _normalize(item[2])) for item in raw_mappings}:
                raw_mappings.append((entity_type, placeholder, raw_value, value_hash))

        protected_text = text
        if replace:
            parts: list[str] = []
            pos = 0
            for finding in findings:
                parts.append(text[pos:finding.start])
                parts.append(finding.placeholder)
                pos = finding.end
            parts.append(text[pos:])
            protected_text = "".join(parts)

        if reversible and persist_mapping and self.vault and doc_id:
            for entity_type, placeholder, raw_value, value_hash in raw_mappings:
                self.vault.store(
                    tenant=tenant,
                    doc_id=doc_id,
                    entity_type=entity_type,
                    placeholder=placeholder,
                    value=raw_value,
                    value_hash=value_hash,
                )
        return ProtectionResult(protected_text=protected_text, findings=findings, raw_mappings=raw_mappings)


def build_detector(
    mode: str,
    *,
    rizzo_url: str = "",
    timeout_seconds: int = 120,
    rizzo_token: str = "",
) -> Detector:
    normalized = mode.strip().lower()
    if normalized == "rizzo_regex":
        return RizzoRegexDetector()
    if normalized == "rizzo_http" and rizzo_url:
        return RizzoHttpDetector(rizzo_url, timeout_seconds=timeout_seconds, token=rizzo_token)
    raise RuntimeError("PRIVACY_DETECTOR must be rizzo_regex, or rizzo_http with RIZZO_BASE_URL")


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
        if overlaps_left or overlaps_right:
            continue
        kept.insert(index, dict(item))
    return kept


def _text_windows(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> Iterator[tuple[str, int]]:
    step = max_chars - overlap_chars
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        yield text[start:end], start
        if end == len(text):
            break
        start += step


def _next_placeholder(entity_type: str, counters: dict[str, int], reserved: set[str]) -> str:
    while True:
        counters[entity_type] = counters.get(entity_type, 0) + 1
        placeholder = f"[{entity_type}_{counters[entity_type]}]"
        if placeholder not in reserved:
            return placeholder


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()
