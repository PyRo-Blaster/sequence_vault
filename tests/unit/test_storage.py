from pathlib import Path

import pytest
from moto import mock_aws

from sequence_vault.adapters.storage.local import LocalObjectStore
from sequence_vault.adapters.storage.s3 import S3ObjectStore


def test_local_store_round_trip_and_rejects_path_tricks(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    store.put("sources/t1/file_1", b"data")
    assert store.get("sources/t1/file_1") == b"data"
    for key in ("../escape", "/etc/passwd", "sources/../../x", "Bad Name.fasta"):
        with pytest.raises(ValueError):
            store.put(key, b"x")


def test_s3_store_round_trip_and_short_links() -> None:
    with mock_aws():
        store = S3ObjectStore("vault", access_key="test", secret_key="test")
        store.client.create_bucket(Bucket="vault")
        store.put("sources/t1/file_1", b"data")
        assert store.get("sources/t1/file_1") == b"data"
        assert store.exists("sources/t1/file_1") and not store.exists("missing")
        url = store.presigned_url("sources/t1/file_1", seconds=3600)
        assert "X-Amz-Expires=300" in url
