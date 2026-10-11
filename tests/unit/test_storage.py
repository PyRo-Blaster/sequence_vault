from pathlib import Path

import pytest
from botocore.exceptions import ClientError
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


@pytest.mark.parametrize("region", ["us-east-1", "eu-central-1"])
def test_s3_store_creates_a_missing_bucket_once_with_versioning(region: str) -> None:
    with mock_aws():
        store = S3ObjectStore("vault", access_key="test", secret_key="test", region=region)
        assert store.ensure_bucket() is True
        assert store.ensure_bucket() is False
        versioning = store.client.get_bucket_versioning(Bucket="vault")
        assert versioning["Status"] == "Enabled"
        store.put("k", b"data")
        assert store.get("k") == b"data"


def test_s3_store_turns_versioning_on_for_an_existing_bucket() -> None:
    """A bucket created without versioning (by hand, or by a start that stopped half-way)
    is versioned at the next start."""
    with mock_aws():
        store = S3ObjectStore("vault", access_key="test", secret_key="test")
        store.client.create_bucket(Bucket="vault")
        assert store.ensure_bucket() is False
        assert store.client.get_bucket_versioning(Bucket="vault")["Status"] == "Enabled"
        store.client.put_bucket_versioning(
            Bucket="vault", VersioningConfiguration={"Status": "Suspended"}
        )
        store.ensure_bucket()
        assert store.client.get_bucket_versioning(Bucket="vault")["Status"] == "Enabled"


@pytest.mark.parametrize("region", ["us-east-1", "eu-central-1"])
def test_s3_store_losing_the_race_to_create_the_bucket_is_fine(
    region: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two replicas both see no bucket; the second create must not fail the start."""
    with mock_aws():
        first = S3ObjectStore("vault", access_key="test", secret_key="test", region=region)
        assert first.ensure_bucket() is True
        second = S3ObjectStore("vault", access_key="test", secret_key="test", region=region)
        missing = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
        monkeypatch.setattr(
            second.client, "head_bucket", lambda **_: (_ for _ in ()).throw(missing)
        )
        second.ensure_bucket()  # us-east-1 accepts re-creating your own bucket; others refuse
        assert second.client.get_bucket_versioning(Bucket="vault")["Status"] == "Enabled"
