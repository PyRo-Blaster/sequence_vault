"""S3-compatible object store (MinIO locally)."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

MAX_LINK_SECONDS = 300


class S3ObjectStore:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        client: "S3Client | None" = None,
    ) -> None:
        self.bucket = bucket
        self.client: S3Client = client or boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "us-east-1",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def ensure_bucket(self) -> bool:
        """Create the bucket, private and versioned, if it does not exist. True if created.

        For a self-hosted MinIO; with a managed S3 bucket, provision it outside the app and
        leave SEQUENCE_VAULT_OBJECT_STORAGE_CREATE_BUCKET off."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return False
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
                raise
        region = self.client.meta.region_name
        if region and region != "us-east-1":
            self.client.create_bucket(
                Bucket=self.bucket,
                CreateBucketConfiguration={"LocationConstraint": region},  # type: ignore[typeddict-item]
            )
        else:
            self.client.create_bucket(Bucket=self.bucket)
        # Versioning keeps overwritten or deleted objects recoverable.
        self.client.put_bucket_versioning(
            Bucket=self.bucket, VersioningConfiguration={"Status": "Enabled"}
        )
        return True

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True

    def presigned_url(self, key: str, seconds: int) -> str:
        """Short-lived download link; callers must re-authorize before asking for one."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=min(seconds, MAX_LINK_SECONDS),
        )
