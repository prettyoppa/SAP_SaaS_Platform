"""후속 질문 메시지 목록 정렬용 유틸 (DB·드라이버에 따라 naive/aware datetime 혼재 시 TypeError 방지)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def followup_created_at_sort_key(message: Any, *, fallback: datetime | None) -> datetime:
    """항상 naive UTC 기준으로 비교 가능한 datetime을 반환합니다."""
    dt = getattr(message, "created_at", None) or fallback
    if dt is None:
        return datetime(1970, 1, 1)
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
