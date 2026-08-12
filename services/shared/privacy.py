from __future__ import annotations

import json
from enum import Enum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator


class PrivacyPolicy(str, Enum):
    OFF = "off"
    DETECT = "detect"
    PROTECT_EGRESS = "protect_egress"
    STRICT = "strict"


class PrivacyDetector(str, Enum):
    RIZZO_REGEX = "rizzo_regex"
    RIZZO_HTTP = "rizzo_http"


class PrivacyEngineMetadata(BaseModel):
    name: str
    version: str
    source_revision: str
    mode: str


class PrivacyFinding(BaseModel):
    type: str
    detector: str
    confidence: float = Field(ge=0.0, le=1.0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    placeholder: str
    value_hash: str
    validated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("end")
    @classmethod
    def validate_end(cls, value: int, info) -> int:
        start = info.data.get("start")
        if isinstance(start, int) and value <= start:
            raise ValueError("end must be greater than start")
        return value


class PrivacyDetectRequest(BaseModel):
    text: str = Field(min_length=1)
    tenant: str = Field(default="default", min_length=1)
    doc_id: str | None = None


class PrivacyDetectResponse(BaseModel):
    findings: list[PrivacyFinding]
    pii_count: int = Field(ge=0)
    pii_types: list[str]
    engine: PrivacyEngineMetadata


class PrivacyPseudonymizeRequest(PrivacyDetectRequest):
    reversible: bool = True
    persist_mapping: bool = True


class PrivacyPseudonymizeResponse(PrivacyDetectResponse):
    protected_text: str
    reversible: bool
    mapping_stored: bool


class PrivacyRestoreRequest(BaseModel):
    text: str = Field(min_length=1)
    tenant: str = Field(default="default", min_length=1)
    doc_id: str = Field(min_length=1)


class PrivacyRestoreResponse(BaseModel):
    restored_text: str
    restored_count: int = Field(ge=0)
    engine: PrivacyEngineMetadata


class PrivacySettings(BaseModel):
    workspace: str = Field(min_length=1, max_length=128)
    privacy_policy: PrivacyPolicy
    privacy_detector: PrivacyDetector
    privacy_mapping_enabled: bool
    vault_key_version: str | None = None
    model: dict[str, Any] | None = None


class PrivacySettingsUpdate(BaseModel):
    workspace: str = Field(default="default", min_length=1, max_length=128)
    privacy_policy: PrivacyPolicy
    privacy_detector: PrivacyDetector
    privacy_mapping_enabled: bool = True


class PrivacyServiceError(RuntimeError):
    pass


class PrivacyClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: int = 30):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def detect(self, request: PrivacyDetectRequest) -> PrivacyDetectResponse:
        body = self._post("/v1/privacy/detect", request.model_dump(mode="json"))
        try:
            return PrivacyDetectResponse.model_validate(body)
        except Exception as exc:
            raise PrivacyServiceError("Privacy service returned a malformed detect response") from exc

    def pseudonymize(self, request: PrivacyPseudonymizeRequest) -> PrivacyPseudonymizeResponse:
        body = self._post("/v1/privacy/pseudonymize", request.model_dump(mode="json"))
        try:
            return PrivacyPseudonymizeResponse.model_validate(body)
        except Exception as exc:
            raise PrivacyServiceError("Privacy service returned a malformed pseudonymize response") from exc

    def restore(self, request: PrivacyRestoreRequest) -> PrivacyRestoreResponse:
        body = self._post("/v1/privacy/restore", request.model_dump(mode="json"))
        try:
            return PrivacyRestoreResponse.model_validate(body)
        except Exception as exc:
            raise PrivacyServiceError("Privacy service returned a malformed restore response") from exc

    def settings(self, workspace: str) -> PrivacySettings:
        body = self._get(f"/v1/privacy/settings?workspace={quote(workspace, safe='')}")
        try:
            return PrivacySettings.model_validate(body)
        except Exception as exc:
            raise PrivacyServiceError("Privacy service returned malformed runtime settings") from exc

    def _get(self, path: str) -> dict[str, Any]:
        request = Request(
            self._base_url + path,
            headers={"x-privacy-token": self._token},
            method="GET",
        )
        return self._request(request)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "x-privacy-token": self._token}
        request = Request(
            self._base_url + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._request(request)

    def _request(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raise PrivacyServiceError(f"Privacy service rejected the request with HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise PrivacyServiceError("Privacy service is unavailable") from exc
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise PrivacyServiceError("Privacy service returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise PrivacyServiceError("Privacy service returned an invalid response shape")
        return body
