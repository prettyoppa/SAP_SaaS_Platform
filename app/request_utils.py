"""HTTP request helpers (proxy / HTTPS behind Railway, etc.)."""

from __future__ import annotations

import os

from fastapi import Request


def is_https_request(request: Request) -> bool:
    """Client-facing HTTPS when behind a TLS-terminating reverse proxy."""
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded == "https":
        return True
    if request.url.scheme == "https":
        return True
    pub = (os.environ.get("PUBLIC_BASE_URL") or "").strip().lower()
    return pub.startswith("https://")
