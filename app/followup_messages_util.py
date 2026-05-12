"""후속 질문 메시지 목록 정렬용 유틸 (DB·드라이버에 따라 naive/aware datetime 혼재 시 TypeError 방지)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _coerce_sort_datetime(raw: Any) -> datetime:
    """정렬 키용: 항상 naive datetime (비교 가능)."""
    if raw is None:
        return datetime(1970, 1, 1)
    if isinstance(raw, datetime):
        if raw.tzinfo is not None and raw.tzinfo.utcoffset(raw) is not None:
            return raw.astimezone(timezone.utc).replace(tzinfo=None)
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    return datetime(1970, 1, 1)


def followup_created_at_sort_key(message: Any, *, fallback: datetime | None) -> datetime:
    """항상 naive 기준으로 비교 가능한 datetime을 반환합니다."""
    created = getattr(message, "created_at", None)
    if created is not None:
        return _coerce_sort_datetime(created)
    return _coerce_sort_datetime(fallback)
