"""플랜 기반 한도: UTC 월간 누적(삭제·취소 시 복구 없음), 건당 AI 문의 레저, 체험판=Junior entitlement."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from . import models
from .subscription_catalog import METRIC_AI_INQUIRY

if TYPE_CHECKING:
    pass

_FALLBACK_AI_INQUIRY_CAP = 60

# Stripe 등 자동 갱신 시 admin이 지정한 플랜을 덮어쓰지 않도록 할 때 사용
SUBSCRIPTION_SOURCE_ADMIN = "admin"


def utc_year_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def experience_trial_active(user: models.User) -> bool:
    end = getattr(user, "experience_trial_ends_at", None)
    if not end:
        return False
    return datetime.utcnow() < end


def subscription_plan_admin_locked(user: models.User) -> bool:
    return (getattr(user, "subscription_plan_source", None) or "").strip().lower() == SUBSCRIPTION_SOURCE_ADMIN


def effective_subscription_plan_code(user: models.User) -> str:
    code = (getattr(user, "subscription_plan_code", None) or "experience").strip() or "experience"
    exp = getattr(user, "subscription_plan_expires_at", None)
    if exp and datetime.utcnow() >= exp:
        return "experience"
    return code


def account_kind_for_user(user: models.User) -> str:
    return "consultant" if getattr(user, "is_consultant", False) else "member"


def plan_row_for_entitlements(db: Session, user: models.User) -> models.SubscriptionPlan | None:
    """
    entitlement 조회용 플랜 행. 관리자는 None(무제한 처리).
    Experience + 체험 기간 중 → consultant + junior 와 동일 한도.
    """
    if not user:
        return None
    if getattr(user, "is_admin", False):
        return None
    kind = account_kind_for_user(user)
    code = effective_subscription_plan_code(user)
    if code == "experience" and experience_trial_active(user):
        kind, code = "consultant", "junior"
    row = (
        db.query(models.SubscriptionPlan)
        .filter(
            models.SubscriptionPlan.account_kind == kind,
            models.SubscriptionPlan.code == code,
            models.SubscriptionPlan.is_active.is_(True),
        )
        .first()
    )
    if row:
        return row
    return (
        db.query(models.SubscriptionPlan)
        .filter(
            models.SubscriptionPlan.account_kind == kind,
            models.SubscriptionPlan.code == "experience",
            models.SubscriptionPlan.is_active.is_(True),
        )
        .first()
    )


def get_user_subscription_plan(db: Session, user: models.User) -> models.SubscriptionPlan | None:
    """호환용 별칭: entitlement 해석에 plan_row_for_entitlements 사용."""
    return plan_row_for_entitlements(db, user)


def get_entitlement(
    db: Session, plan: models.SubscriptionPlan, metric_key: str
) -> models.PlanEntitlement | None:
    return (
        db.query(models.PlanEntitlement)
        .filter(
            models.PlanEntitlement.plan_id == plan.id,
            models.PlanEntitlement.metric_key == metric_key,
        )
        .first()
    )


def monthly_entitlement_cap(db: Session, user: models.User, metric_key: str) -> int | None:
    if not user or getattr(user, "is_admin", False):
        return None
    plan = plan_row_for_entitlements(db, user)
    if not plan:
        return 0
    ent = get_entitlement(db, plan, metric_key)
    if not ent:
        return 0
    pt = (ent.period_type or "").strip().lower()
    if pt == "disabled":
        return 0
    if pt == "unlimited":
        return None
    if pt == "monthly":
        return int(ent.limit_value if ent.limit_value is not None else 0)
    return 0


def per_request_entitlement_cap(db: Session, user: models.User, metric_key: str) -> int | None:
    if not user or getattr(user, "is_admin", False):
        return None
    plan = plan_row_for_entitlements(db, user)
    if not plan:
        return 0
    ent = get_entitlement(db, plan, metric_key)
    if not ent:
        return 0
    pt = (ent.period_type or "").strip().lower()
    if pt == "disabled":
        return 0
    if pt == "unlimited":
        return None
    if pt == "per_request":
        return int(ent.limit_value if ent.limit_value is not None else 0)
    return 0


def get_monthly_used(db: Session, user_id: int, metric_key: str, year_month: str | None = None) -> int:
    ym = year_month or utc_year_month()
    row = (
        db.query(models.SubscriptionUsageMonthly)
        .filter(
            models.SubscriptionUsageMonthly.user_id == int(user_id),
            models.SubscriptionUsageMonthly.metric_key == metric_key,
            models.SubscriptionUsageMonthly.year_month == ym,
        )
        .first()
    )
    return int(row.used) if row else 0


def monthly_quota_exceeded(db: Session, user: models.User, metric_key: str, add_amount: int = 1) -> bool:
    if not user or getattr(user, "is_admin", False):
        return False
    cap = monthly_entitlement_cap(db, user, metric_key)
    if cap is None:
        return False
    if cap == 0:
        return True
    used = get_monthly_used(db, user.id, metric_key)
    return used + int(add_amount) > cap


def consume_monthly(db: Session, user: models.User, metric_key: str, amount: int = 1) -> None:
    if not user or getattr(user, "is_admin", False):
        return
    ym = utc_year_month()
    row = (
        db.query(models.SubscriptionUsageMonthly)
        .filter(
            models.SubscriptionUsageMonthly.user_id == user.id,
            models.SubscriptionUsageMonthly.metric_key == metric_key,
            models.SubscriptionUsageMonthly.year_month == ym,
        )
        .first()
    )
    if row is None:
        row = models.SubscriptionUsageMonthly(
            user_id=user.id,
            metric_key=metric_key,
            year_month=ym,
            used=int(amount),
        )
        db.add(row)
    else:
        row.used = int(row.used) + int(amount)


def try_consume_monthly(db: Session, user: models.User, metric_key: str, amount: int = 1) -> str | None:
    """
    월간(UTC) 한도 소비. 실패 시 이유 코드.
    반환: None=성공, 'disabled', 'monthly_limit'
    """
    if not user or getattr(user, "is_admin", False):
        consume_monthly(db, user, metric_key, amount)
        return None
    cap = monthly_entitlement_cap(db, user, metric_key)
    if cap == 0:
        return "disabled"
    if cap is None:
        consume_monthly(db, user, metric_key, amount)
        return None
    used = get_monthly_used(db, user.id, metric_key)
    if used + int(amount) > cap:
        return "monthly_limit"
    consume_monthly(db, user, metric_key, amount)
    return None


def get_per_request_metric_used(
    db: Session, user_id: int, metric_key: str, request_kind: str, request_id: int
) -> int:
    rk = (request_kind or "").strip().lower()
    row = (
        db.query(models.SubscriptionUsagePerRequest)
        .filter(
            models.SubscriptionUsagePerRequest.user_id == int(user_id),
            models.SubscriptionUsagePerRequest.metric_key == metric_key,
            models.SubscriptionUsagePerRequest.request_kind == rk,
            models.SubscriptionUsagePerRequest.request_id == int(request_id),
        )
        .first()
    )
    return int(row.used) if row else 0


def try_consume_per_request(
    db: Session,
    user: models.User,
    metric_key: str,
    request_kind: str,
    request_id: int,
    amount: int = 1,
) -> str | None:
    """건당(per_request) entitlement. 'disabled' | 'per_request_limit' | None"""
    if not user or getattr(user, "is_admin", False):
        _bump_per_request(db, user.id, metric_key, request_kind, request_id, amount)
        return None
    cap = per_request_entitlement_cap(db, user, metric_key)
    if cap == 0:
        return "disabled"
    if cap is None:
        _bump_per_request(db, user.id, metric_key, request_kind, request_id, amount)
        return None
    used = get_per_request_metric_used(db, user.id, metric_key, request_kind, request_id)
    if used + int(amount) > cap:
        return "per_request_limit"
    _bump_per_request(db, user.id, metric_key, request_kind, request_id, amount)
    return None


def _bump_per_request(
    db: Session,
    user_id: int,
    metric_key: str,
    request_kind: str,
    request_id: int,
    amount: int,
) -> None:
    rk = (request_kind or "").strip().lower()
    row = (
        db.query(models.SubscriptionUsagePerRequest)
        .filter(
            models.SubscriptionUsagePerRequest.user_id == int(user_id),
            models.SubscriptionUsagePerRequest.metric_key == metric_key,
            models.SubscriptionUsagePerRequest.request_kind == rk,
            models.SubscriptionUsagePerRequest.request_id == int(request_id),
        )
        .first()
    )
    if row is None:
        row = models.SubscriptionUsagePerRequest(
            user_id=int(user_id),
            metric_key=metric_key,
            request_kind=rk,
            request_id=int(request_id),
            used=int(amount),
        )
        db.add(row)
    else:
        row.used = int(row.used) + int(amount)


def count_ai_inquiry_user_turns(
    db: Session, user_id: int, request_kind: str, request_id: int
) -> int:
    rk = (request_kind or "").strip().lower()
    if rk == "rfp":
        return (
            db.query(models.RfpFollowupMessage)
            .filter(
                models.RfpFollowupMessage.rfp_id == int(request_id),
                models.RfpFollowupMessage.role == "user",
            )
            .count()
        )
    if rk == "analysis":
        return (
            db.query(models.AbapAnalysisFollowupMessage)
            .filter(
                models.AbapAnalysisFollowupMessage.request_id == int(request_id),
                models.AbapAnalysisFollowupMessage.role == "user",
            )
            .count()
        )
    if rk == "integration":
        return (
            db.query(models.IntegrationFollowupMessage)
            .filter(
                models.IntegrationFollowupMessage.request_id == int(request_id),
                models.IntegrationFollowupMessage.role == "user",
            )
            .count()
        )
    return 0


def get_ai_inquiry_used(db: Session, user_id: int, request_kind: str, request_id: int) -> int:
    """레저 우선(삭제해도 감소하지 않음). 레저 없으면 메시지 수."""
    rk = (request_kind or "").strip().lower()
    row = (
        db.query(models.SubscriptionUsagePerRequest)
        .filter(
            models.SubscriptionUsagePerRequest.user_id == int(user_id),
            models.SubscriptionUsagePerRequest.metric_key == METRIC_AI_INQUIRY,
            models.SubscriptionUsagePerRequest.request_kind == rk,
            models.SubscriptionUsagePerRequest.request_id == int(request_id),
        )
        .first()
    )
    n_msg = count_ai_inquiry_user_turns(db, user_id, request_kind, request_id)
    if row is None:
        return int(n_msg)
    return max(int(row.used), int(n_msg))


def record_ai_inquiry_user_turn(
    db: Session, user_id: int, request_kind: str, request_id: int, *, ledger_after: int
) -> None:
    """사용자 AI 문의 1턴 반영: ledger_after = (이번 POST 직전 effective used) + 1."""
    rk = (request_kind or "").strip().lower()
    row = (
        db.query(models.SubscriptionUsagePerRequest)
        .filter(
            models.SubscriptionUsagePerRequest.user_id == int(user_id),
            models.SubscriptionUsagePerRequest.metric_key == METRIC_AI_INQUIRY,
            models.SubscriptionUsagePerRequest.request_kind == rk,
            models.SubscriptionUsagePerRequest.request_id == int(request_id),
        )
        .first()
    )
    if row is None:
        row = models.SubscriptionUsagePerRequest(
            user_id=int(user_id),
            metric_key=METRIC_AI_INQUIRY,
            request_kind=rk,
            request_id=int(request_id),
            used=int(ledger_after),
        )
        db.add(row)
    else:
        row.used = max(int(row.used), int(ledger_after))


def ai_inquiry_cap_per_request(db: Session, user: models.User | None) -> int | None:
    if not user:
        return _FALLBACK_AI_INQUIRY_CAP
    if getattr(user, "is_admin", False):
        return None
    plan = plan_row_for_entitlements(db, user)
    if not plan:
        return _FALLBACK_AI_INQUIRY_CAP
    ent = get_entitlement(db, plan, METRIC_AI_INQUIRY)
    if not ent:
        return _FALLBACK_AI_INQUIRY_CAP
    if ent.period_type == "disabled":
        return 0
    if ent.period_type == "unlimited":
        return None
    if ent.period_type == "per_request":
        return int(ent.limit_value if ent.limit_value is not None else 0)
    return int(ent.limit_value) if ent.limit_value is not None else _FALLBACK_AI_INQUIRY_CAP


def ai_inquiry_limit_reached(cap: int | None, used: int) -> bool:
    if cap is None:
        return False
    return used >= cap


def ai_inquiry_snapshot(
    db: Session,
    user: models.User | None,
    request_kind: str,
    request_id: int,
) -> dict:
    cap = ai_inquiry_cap_per_request(db, user)
    used = (
        get_ai_inquiry_used(db, user.id, request_kind, request_id)
        if user
        else 0
    )
    reached = ai_inquiry_limit_reached(cap, used)
    max_turns_display = 10**9 if cap is None else int(cap)
    return {
        "cap": cap,
        "used": used,
        "reached": reached,
        "max_turns_display": max_turns_display,
        "unlimited": cap is None,
    }
