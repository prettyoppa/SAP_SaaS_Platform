"""First-visit / anonymous language hint from request headers."""
from __future__ import annotations

from fastapi import Request


def initial_lang_from_request(request: Request) -> str:
    """
    Pre-login default: KR → ko; any other known country → en;
    geo unknown → en (회사 노트북 등 ko Accept-Language만 있는 해외 접속 대비).
    """
    q = (request.query_params.get("lang") or "").strip().lower()
    if q in ("ko", "en"):
        return q

    country = (request.headers.get("CF-IPCountry") or "").strip().upper()
    if country == "KR":
        return "ko"
    if country:
        return "en"
    return "en"
