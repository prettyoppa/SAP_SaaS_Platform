"""AI 선불 잔액(원화) · 계좌이체 충전."""

from __future__ import annotations

WALLET_TOPUP_PLAN_CODE = "ai_wallet_topup"
DEFAULT_MIN_TOPUP_KRW = 30_000
MIN_TOPUP_KRW = DEFAULT_MIN_TOPUP_KRW  # backward-compatible alias
MIN_TOPUP_SETTING_KEY = "ai_wallet_min_topup_krw"


def min_topup_krw(db) -> int:
    from . import models

    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == MIN_TOPUP_SETTING_KEY)
        .first()
    )
    raw = (row.value if row else "") or ""
    try:
        n = int(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return DEFAULT_MIN_TOPUP_KRW
    return n if n > 0 else DEFAULT_MIN_TOPUP_KRW


def wallet_balance_krw(user) -> int:
    return int(getattr(user, "ai_wallet_balance_krw", None) or 0)


def apply_wallet_credit(user, amount_krw: int) -> int:
    """원화 잔액에 amount를 더하고 갱신된 잔액을 반환."""
    new_bal = wallet_balance_krw(user) + int(amount_krw)
    user.ai_wallet_balance_krw = new_bal
    return new_bal


def apply_wallet_debit(user, amount_krw: int) -> int:
    """충전 신청 취소·거절 시 선반영분 회수."""
    new_bal = wallet_balance_krw(user) - int(amount_krw)
    user.ai_wallet_balance_krw = new_bal
    return new_bal


def is_wallet_topup_plan_code(plan_code: str | None) -> bool:
    return (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE


def claim_plan_label_ko(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI 크레딧 충전"
    return plan_code or "—"


def claim_plan_label_en(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI credit top-up"
    return plan_code or "—"
