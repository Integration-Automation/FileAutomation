"""S3 client (Singleton Facade around ``boto3``)."""

from __future__ import annotations

from typing import Any

from automation_file.logging_config import file_automation_logger


def _import_boto3() -> Any:
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError(
            "boto3 import failed — reinstall `automation_file` to restore the S3 backend"
        ) from error
    return boto3


class S3Client:
    """Lazy wrapper around ``boto3.client('s3', ...)``."""

    def __init__(self) -> None:
        self.client: Any = None

    def later_init(
        self,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> Any:
        """Build a boto3 S3 client. Arguments default to the standard AWS chain."""
        boto3 = _import_boto3()
        self.client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        file_automation_logger.info("S3Client: client ready (region=%s)", region_name)
        return self.client

    def require_client(self) -> Any:
        if self.client is None:
            raise RuntimeError("S3Client not initialised; call later_init() first")
        return self.client


s3_instance: S3Client = S3Client()
