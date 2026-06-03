"""AI 크레딧 — 누구에게 기록·차감할지, AI 시작 전 잔액 확인."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .ai_usage_recorder import FALLBACK_COST_USD_MICRO, AiUsageContext


def user_skips_wallet(user: Any | None) -> bool:
    """플랫폼 관리자만 선불 잔액·차감 검사 생략."""
    return bool(user and getattr(user, "is_admin", False))


def delivery_job_billing_user_id(actor_user_id: int) -> int:
    """
    FS·납품 코드 등 컨설턴트/관리자가 실행한 납품 AI 작업.
    요청 소유자가 아니라 작업을 시작한 계정에 사용 내역·차감을 남긴다.
    """
    return int(actor_user_id)


def ai_usage_context_for_delivery_job(
    *,
    billing_user_id: int,
    request_kind: str,
    request_id: int,
) -> AiUsageContext:
    return AiUsageContext(
        user_id=int(billing_user_id),
        request_kind=request_kind,
        request_id=int(request_id),
    )


def skips_delivery_wallet_preflight(user: Any | None) -> bool:
    return user_skips_wallet(user)


def estimated_stage_cost_krw(db: Session, stage: str) -> int:
    from .ai_usage_pricing import billable_usd_micro
    from .ai_wallet import krw_from_usage_usd_micro, usd_krw_rate_from_db

    st = (stage or "other").strip()
    raw_micro = FALLBACK_COST_USD_MICRO.get(st) or FALLBACK_COST_USD_MICRO["other"]
    micro = billable_usd_micro(db, raw_micro)
    return krw_from_usage_usd_micro(micro, usd_krw_rate_from_db(db))


def wallet_preflight_for_ai_stage(
    db: Session, user: Any | None, *, stage: str
) -> str | None:
    """
    AI 기능 시작 전. 잔액이 해당 단계 추정 비용 미만이면 wallet_insufficient.
    일반회원·컨설턴트는 잔액 0 이하에서 AI 사용 불가.
    """
    if not user:
        return "forbidden"
    if user_skips_wallet(user):
        return None
    from .ai_wallet import wallet_balance_krw

    need_krw = estimated_stage_cost_krw(db, stage)
    bal = wallet_balance_krw(user)
    if bal < max(1, need_krw):
        return "wallet_insufficient"
    return None


def wallet_preflight_for_delivery_stage(
    db: Session, user: Any | None, *, stage: str
) -> str | None:
    """납품 FS·개발코드 등 — wallet_preflight_for_ai_stage 와 동일."""
    return wallet_preflight_for_ai_stage(db, user, stage=stage)
