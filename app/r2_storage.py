"""Cloudflare R2 (S3-compatible) uploads for RFP attachments."""

from __future__ import annotations

import io
import os
import time
import uuid
from typing import BinaryIO, Optional, Tuple

R2_PREFIX = "r2://"


def is_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
        )
    )


def parse_storage_ref(file_path: Optional[str]) -> Tuple[str, str]:
    """Returns ('r2', key) or ('local', path)."""
    if not file_path:
        return "local", ""
    if file_path.startswith(R2_PREFIX):
        return "r2", file_path[len(R2_PREFIX) :]
    return "local", file_path


def _client():
    import boto3
    from botocore.config import Config

    account_id = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(user_id: int, ext: str, data: bytes, content_type: str) -> str:
    """Uploads to R2 and returns DB value (r2://...)."""
    key = f"rfp_attachments/{user_id}/{int(time.time())}_{uuid.uuid4().hex}{ext}"
    bucket = os.environ["R2_BUCKET_NAME"]
    bio = io.BytesIO(data)
    _client().upload_fileobj(
        bio,
        Bucket=bucket,
        Key=key,
        ExtraArgs={"ContentType": content_type or "application/octet-stream"},
    )
    return f"{R2_PREFIX}{key}"


def upload_fileobj(user_id: int, ext: str, fileobj: BinaryIO, content_type: str) -> str:
    key = f"rfp_attachments/{user_id}/{int(time.time())}_{uuid.uuid4().hex}{ext}"
    bucket = os.environ["R2_BUCKET_NAME"]
    _client().upload_fileobj(
        fileobj,
        Bucket=bucket,
        Key=key,
        ExtraArgs={"ContentType": content_type or "application/octet-stream"},
    )
    return f"{R2_PREFIX}{key}"


def delete_if_r2_uri(file_path: Optional[str]) -> None:
    kind, ref = parse_storage_ref(file_path)
    if kind != "r2" or not ref:
        return
    bucket = os.environ.get("R2_BUCKET_NAME")
    if not bucket:
        return
    try:
        _client().delete_object(Bucket=bucket, Key=ref)
    except Exception:
        pass


def presigned_get_url(key: str, download_filename: str, expires_in: int = 3600) -> str:
    bucket = os.environ["R2_BUCKET_NAME"]
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{download_filename}"',
        },
        ExpiresIn=expires_in,
    )
