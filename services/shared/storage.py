from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote

from services.shared.config import RuntimeConfig


class ObjectStorage(Protocol):
    def upload_bytes(self, bucket_name: str, object_name: str, payload: bytes, content_type: str) -> str: ...
    def upload_bytes_immutable(
        self, *, bucket_name: str, object_name: str, payload: bytes, content_type: str
    ) -> dict[str, str | int]: ...
    def download_bytes(self, uri: str) -> bytes: ...
    def delete_gs_uri(self, uri: str, if_generation_match: int | None = None) -> bool: ...
    def get_blob_size(self, uri: str) -> int: ...
    def generate_upload_signed_url(
        self, bucket_name: str, object_name: str, content_type: str, expiration_minutes: int
    ) -> str: ...
    def bucket_hardening_status(self, bucket_name: str) -> dict[str, str | bool | None]: ...


class GCSStorageClient:
    def __init__(self, project_id: str):
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import storage

        self._google_auth = google.auth
        self.client = storage.Client(project=project_id)
        self._auth_request = Request()

    def upload_bytes(self, bucket_name: str, object_name: str, payload: bytes, content_type: str) -> str:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(payload, content_type=content_type)
        return f"gs://{bucket_name}/{object_name}"

    def upload_bytes_immutable(
        self,
        *,
        bucket_name: str,
        object_name: str,
        payload: bytes,
        content_type: str,
    ) -> dict[str, str | int]:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(payload, content_type=content_type, if_generation_match=0)
        return {
            "gs_uri": f"gs://{bucket_name}/{object_name}",
            "generation": int(blob.generation or 0),
            "metageneration": int(blob.metageneration or 0),
        }

    def download_bytes(self, uri: str) -> bytes:
        bucket, object_name = parse_gs_uri(uri)
        return self.client.bucket(bucket).blob(object_name).download_as_bytes()

    def delete_gs_uri(self, uri: str, if_generation_match: int | None = None) -> bool:
        from google.api_core.exceptions import NotFound

        bucket_name, object_name = parse_gs_uri(uri)
        blob = self.client.bucket(bucket_name).blob(object_name)
        kwargs: dict[str, int] = {}
        if if_generation_match is not None and int(if_generation_match) > 0:
            kwargs["if_generation_match"] = int(if_generation_match)
        try:
            blob.delete(**kwargs)
            return True
        except NotFound:
            return False

    def get_blob_size(self, uri: str) -> int:
        bucket, object_name = parse_gs_uri(uri)
        blob = self.client.bucket(bucket).get_blob(object_name)
        if blob is None:
            raise FileNotFoundError(uri)
        return int(blob.size or 0)

    def generate_upload_signed_url(
        self,
        bucket_name: str,
        object_name: str,
        content_type: str,
        expiration_minutes: int,
    ) -> str:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        credentials, _ = self._google_auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(self._auth_request)
        signer_email = getattr(credentials, "service_account_email", None)
        if signer_email and credentials.token:
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=expiration_minutes),
                method="PUT",
                content_type=content_type,
                service_account_email=signer_email,
                access_token=credentials.token,
            )
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="PUT",
            content_type=content_type,
        )

    def bucket_hardening_status(self, bucket_name: str) -> dict[str, str | bool | None]:
        bucket = self.client.get_bucket(bucket_name)
        return {
            "ubla": bool(bucket.iam_configuration.uniform_bucket_level_access_enabled),
            "public_access_prevention": bucket.iam_configuration.public_access_prevention,
            "default_kms_key_name": bucket.default_kms_key_name,
        }


class LocalStorageClient:
    """Filesystem-backed object storage with stable local:// URIs."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_bytes(self, bucket_name: str, object_name: str, payload: bytes, content_type: str) -> str:
        path = self._path(bucket_name, object_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return _local_uri(bucket_name, object_name)

    def upload_bytes_immutable(
        self,
        *,
        bucket_name: str,
        object_name: str,
        payload: bytes,
        content_type: str,
    ) -> dict[str, str | int]:
        path = self._path(bucket_name, object_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
        stat = path.stat()
        return {
            "gs_uri": _local_uri(bucket_name, object_name),
            "generation": int(stat.st_mtime_ns),
            "metageneration": 1,
        }

    def download_bytes(self, uri: str) -> bytes:
        bucket, object_name = parse_local_uri(uri)
        return self._path(bucket, object_name).read_bytes()

    def delete_gs_uri(self, uri: str, if_generation_match: int | None = None) -> bool:
        bucket, object_name = parse_local_uri(uri)
        path = self._path(bucket, object_name)
        if not path.exists():
            return False
        if if_generation_match is not None and if_generation_match > 0:
            if path.stat().st_mtime_ns != int(if_generation_match):
                raise RuntimeError("Local object generation mismatch")
        path.unlink()
        return True

    def get_blob_size(self, uri: str) -> int:
        bucket, object_name = parse_local_uri(uri)
        return self._path(bucket, object_name).stat().st_size

    def generate_upload_signed_url(
        self,
        bucket_name: str,
        object_name: str,
        content_type: str,
        expiration_minutes: int,
    ) -> str:
        raise NotImplementedError("Signed uploads are only available with STORAGE_BACKEND=gcs")

    def bucket_hardening_status(self, bucket_name: str) -> dict[str, str | bool | None]:
        self._path(bucket_name, ".keep").parent.mkdir(parents=True, exist_ok=True)
        return {
            "ubla": True,
            "public_access_prevention": "filesystem-boundary",
            "default_kms_key_name": None,
        }

    def _path(self, bucket_name: str, object_name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", bucket_name or ""):
            raise ValueError("Invalid local storage namespace")
        normalized = PurePosixPath(object_name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
            raise ValueError("Invalid local object path")
        candidate = (self.root / bucket_name / Path(*normalized.parts)).resolve()
        namespace_root = (self.root / bucket_name).resolve()
        if os.path.commonpath([str(candidate), str(namespace_root)]) != str(namespace_root):
            raise ValueError("Local object path escapes storage root")
        return candidate


def build_storage_client(config: RuntimeConfig) -> ObjectStorage:
    if config.storage_backend == "filesystem":
        return LocalStorageClient(config.local_storage_path)
    if config.storage_backend == "gcs":
        return GCSStorageClient(config.project_id)
    raise RuntimeError(f"Unsupported storage backend: {config.storage_backend}")


# Backwards-compatible name for code importing the original GCP implementation.
StorageClient = GCSStorageClient


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("URI must start with gs://")
    return _split_uri_path(uri[len("gs://") :])


def parse_local_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("local://"):
        raise ValueError("URI must start with local://")
    return _split_uri_path(uri[len("local://") :])


def parse_storage_uri(uri: str) -> tuple[str, str, str]:
    if uri.startswith("gs://"):
        bucket, object_name = parse_gs_uri(uri)
        return "gs", bucket, object_name
    if uri.startswith("local://"):
        bucket, object_name = parse_local_uri(uri)
        return "local", bucket, object_name
    raise ValueError("URI must start with gs:// or local://")


def _split_uri_path(path: str) -> tuple[str, str]:
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("URI must include namespace and object path")
    return parts[0], parts[1]


def _local_uri(bucket_name: str, object_name: str) -> str:
    return f"local://{bucket_name}/{object_name.replace(chr(92), '/')}"


def safe_object_name(name: str) -> str:
    return quote(name, safe="-_.~/")
