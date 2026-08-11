from pathlib import Path

import pytest

from services.shared.storage import LocalStorageClient, parse_storage_uri


def test_local_storage_round_trip_and_immutable_write(tmp_path: Path) -> None:
    storage = LocalStorageClient(str(tmp_path))
    uri = storage.upload_bytes("raw", "tenant/doc.txt", b"hello", "text/plain")

    assert uri == "local://raw/tenant/doc.txt"
    assert storage.download_bytes(uri) == b"hello"
    assert storage.get_blob_size(uri) == 5
    assert parse_storage_uri(uri) == ("local", "raw", "tenant/doc.txt")

    result = storage.upload_bytes_immutable(
        bucket_name="reports",
        object_name="tenant/report.json",
        payload=b"{}",
        content_type="application/json",
    )
    assert result["gs_uri"] == "local://reports/tenant/report.json"
    with pytest.raises(FileExistsError):
        storage.upload_bytes_immutable(
            bucket_name="reports",
            object_name="tenant/report.json",
            payload=b"changed",
            content_type="application/json",
        )


def test_local_storage_rejects_path_escape(tmp_path: Path) -> None:
    storage = LocalStorageClient(str(tmp_path))
    with pytest.raises(ValueError, match="Invalid local object path"):
        storage.upload_bytes("raw", "../outside.txt", b"bad", "text/plain")
