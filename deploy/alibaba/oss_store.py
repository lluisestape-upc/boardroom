"""Alibaba Cloud OSS integration — project uploads and published reviews.

This file (together with backend/app/qwen_client.py, which calls Qwen models on
Alibaba Cloud Model Studio) is the repository's **Alibaba Cloud deployment
proof** for the hackathon submission: it uses the official ``oss2`` SDK against
an OSS bucket.

Configuration via environment only (never hardcode credentials):

    OSS_ENDPOINT           e.g. https://oss-eu-central-1.aliyuncs.com
    OSS_BUCKET             bucket name
    OSS_ACCESS_KEY_ID      RAM user access key
    OSS_ACCESS_KEY_SECRET  RAM user secret

When these are unset, the backend runs in local-disk mode and OSS is skipped —
reviews still work; they just aren't published to the bucket.
"""

from __future__ import annotations

import os
from pathlib import Path

import oss2


class OssNotConfigured(RuntimeError):
    """Raised when OSS env vars are missing and an OSS operation was requested."""


def _bucket() -> oss2.Bucket:
    endpoint = os.environ.get("OSS_ENDPOINT")
    bucket = os.environ.get("OSS_BUCKET")
    key_id = os.environ.get("OSS_ACCESS_KEY_ID")
    key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET")
    if not all((endpoint, bucket, key_id, key_secret)):
        raise OssNotConfigured(
            "OSS_ENDPOINT / OSS_BUCKET / OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET "
            "must all be set for OSS publishing"
        )
    auth = oss2.Auth(key_id, key_secret)
    return oss2.Bucket(auth, endpoint, bucket)


def is_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("OSS_ENDPOINT", "OSS_BUCKET", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET")
    )


def upload_project_archive(session_id: str, archive_path: str | Path) -> str:
    """Store an uploaded KiCad project archive. Returns the object key."""
    key = f"projects/{session_id}/{Path(archive_path).name}"
    _bucket().put_object_from_file(key, str(archive_path))
    return key


def publish_review(session_id: str, review_json_path: str | Path) -> str:
    """Publish a signed review.json. Returns the object key."""
    key = f"reviews/{session_id}/review.json"
    _bucket().put_object_from_file(key, str(review_json_path))
    return key


def publish_render(session_id: str, image_path: str | Path) -> str:
    """Publish a board render referenced by the review's board_region entries."""
    key = f"reviews/{session_id}/{Path(image_path).name}"
    _bucket().put_object_from_file(key, str(image_path))
    return key
