"""AI 선불 잔액(원화) · 계좌이체 충전."""

from __future__ import annotations

WALLET_TOPUP_PLAN_CODE = "ai_wallet_topup"
MIN_TOPUP_KRW = 10_000


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
