from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage


class StorageClient:
    def __init__(self, project_id: str):
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

    def download_bytes(self, gs_uri: str) -> bytes:
        bucket, object_name = parse_gs_uri(gs_uri)
        blob = self.client.bucket(bucket).blob(object_name)
        return blob.download_as_bytes()

    def get_blob_size(self, gs_uri: str) -> int:
        bucket, object_name = parse_gs_uri(gs_uri)
        blob = self.client.bucket(bucket).get_blob(object_name)
        if blob is None:
            raise FileNotFoundError(gs_uri)
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
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(self._auth_request)
        signer_email = getattr(credentials, "service_account_email", None)

        # Cloud Run metadata credentials do not carry a private key. Using
        # access token + service account email lets Cloud Storage sign via IAM.
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


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("URI must start with gs://")
    path = uri[len("gs://") :]
    parts = path.split("/", 1)
    if len(parts) != 2:
        raise ValueError("URI must include object path")
    return parts[0], parts[1]


def safe_object_name(name: str) -> str:
    return quote(name, safe="-_.~/")
