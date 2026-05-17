"""AI 선불 잔액(원화) · 계좌이체 충전."""

from __future__ import annotations

WALLET_TOPUP_PLAN_CODE = "ai_wallet_topup"
MIN_TOPUP_KRW = 10_000


def wallet_balance_krw(user) -> int:
    return int(getattr(user, "ai_wallet_balance_krw", None) or 0)


def claim_plan_label_ko(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI 크레딧 충전"
    return plan_code or "—"


def claim_plan_label_en(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI credit top-up"
    return plan_code or "—"
