"""AI 사용량 청구 단가 — Admin 환율·마진(마크업) 적용."""

from __future__ import annotations

MARKUP_PERCENT_SETTING_KEY = "ai_usage_markup_percent"
DEFAULT_MARKUP_PERCENT = 30.0


def ai_usage_markup_percent_from_db(db) -> float:
    from . import models

    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == MARKUP_PERCENT_SETTING_KEY)
        .first()
    )
    raw = (row.value if row else "") or str(DEFAULT_MARKUP_PERCENT)
    try:
        pct = float(str(raw).strip().replace(",", ""))
    except ValueError:
        pct = DEFAULT_MARKUP_PERCENT
    return max(0.0, min(500.0, pct))


def ai_usage_markup_multiplier(db) -> float:
    """1.0 + (마진 % / 100). 예: 30 → 1.30"""
    return 1.0 + ai_usage_markup_percent_from_db(db) / 100.0


def billable_usd_micro(db, raw_micro: int) -> int:
    """API·fallback 원가(micro USD)에 마진을 반영한 청구 micro USD."""
    raw = max(0, int(raw_micro))
    if raw <= 0:
        return 0
    mult = ai_usage_markup_multiplier(db)
    return max(1, int(round(raw * mult)))
