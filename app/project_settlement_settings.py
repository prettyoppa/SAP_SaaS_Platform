"""납품 대금 — 플랫폼 수수료율(SiteSettings)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models

SETTING_PLATFORM_FEE_BPS = "project_settlement_platform_fee_bps"
DEFAULT_PLATFORM_FEE_BPS = 1000  # 10.00%


def get_platform_fee_bps(db: Session) -> int:
    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == SETTING_PLATFORM_FEE_BPS)
        .first()
    )
    if not row or not (row.value or "").strip():
        return DEFAULT_PLATFORM_FEE_BPS
    try:
        v = int(str(row.value).strip())
    except (TypeError, ValueError):
        return DEFAULT_PLATFORM_FEE_BPS
    return max(0, min(v, 5000))


def set_platform_fee_bps(db: Session, bps: int) -> None:
    bps = max(0, min(int(bps), 5000))
    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == SETTING_PLATFORM_FEE_BPS)
        .first()
    )
    if row:
        row.value = str(bps)
    else:
        db.add(models.SiteSettings(key=SETTING_PLATFORM_FEE_BPS, value=str(bps)))


def fee_amounts_krw(gross_krw: int, fee_bps: int) -> tuple[int, int]:
    """(platform_fee_krw, consultant_payout_krw)."""
    gross = max(0, int(gross_krw))
    fee = (gross * int(fee_bps) + 4999) // 10000
    return fee, gross - fee


def format_fee_percent(bps: int) -> str:
    return f"{bps / 100:.2f}".rstrip("0").rstrip(".")
