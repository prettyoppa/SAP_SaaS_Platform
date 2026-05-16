"""계좌이체 입금 신청·Admin 확인."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .subscription_catalog import resolve_plan_monthly_prices
from .subscription_quota import SUBSCRIPTION_SOURCE_ADMIN

CLAIM_STATUS_PENDING = "pending"
CLAIM_STATUS_CONFIRMED = "confirmed"
CLAIM_STATUS_REJECTED = "rejected"
CLAIM_STATUS_CANCELLED = "cancelled"


def account_kind_for_user(user: models.User) -> str:
    return "consultant" if getattr(user, "is_consultant", False) else "member"


def expected_amount_minor(
    db: Session,
    *,
    account_kind: str,
    plan_code: str,
    billing_country: str,
) -> tuple[int | None, str | None]:
    row = (
        db.query(models.SubscriptionPlan)
        .filter(
            models.SubscriptionPlan.account_kind == account_kind,
            models.SubscriptionPlan.code == plan_code,
            models.SubscriptionPlan.is_active.is_(True),
        )
        .first()
    )
    if not row:
        return None, "플랜을 찾을 수 없습니다."
    krw, usd_cents = resolve_plan_monthly_prices(row)
    if billing_country == "KR":
        if krw is None or krw <= 0:
            return None, "이 플랜은 원화 결제 금액이 설정되지 않았습니다."
        return int(krw), None
    if billing_country == "US":
        if usd_cents is None or usd_cents <= 0:
            return None, "이 플랜은 USD 결제 금액이 설정되지 않았습니다."
        return int(usd_cents), None
    return None, "지원하지 않는 국가입니다."


def user_pending_claim(db: Session, user_id: int) -> models.PaymentClaim | None:
    return (
        db.query(models.PaymentClaim)
        .filter(
            models.PaymentClaim.user_id == int(user_id),
            models.PaymentClaim.status == CLAIM_STATUS_PENDING,
        )
        .order_by(models.PaymentClaim.created_at.desc())
        .first()
    )


def create_payment_claim(
    db: Session,
    user: models.User,
    *,
    billing_country: str,
    plan_code: str,
    amount_minor: int,
    depositor_name: str,
    transfer_date: datetime | None,
    member_note: str = "",
) -> tuple[models.PaymentClaim | None, str | None]:
    bc = (billing_country or "").strip().upper()
    if bc not in ("KR", "US"):
        return None, "한국(KR) 또는 미국(US)만 선택할 수 있습니다."
    currency = "KRW" if bc == "KR" else "USD"
    kind = account_kind_for_user(user)
    code = (plan_code or "").strip()[:32]
    if not code:
        return None, "플랜을 선택해 주세요."
    expected, err = expected_amount_minor(db, account_kind=kind, plan_code=code, billing_country=bc)
    if err:
        return None, err
    if int(amount_minor) != int(expected):
        return None, f"입금 금액이 플랜 요금과 일치하지 않습니다. (필요: {expected:,})"
    if user_pending_claim(db, user.id):
        return None, "이미 처리 대기 중인 입금 신청이 있습니다."
    dep = (depositor_name or "").strip()[:200]
    if not dep:
        return None, "입금자명을 입력해 주세요."
    row = models.PaymentClaim(
        user_id=int(user.id),
        status=CLAIM_STATUS_PENDING,
        billing_country=bc,
        currency=currency,
        amount_minor=int(amount_minor),
        plan_account_kind=kind,
        plan_code=code,
        billing_period="monthly",
        depositor_name=dep,
        transfer_date=transfer_date,
        member_note=(member_note or "").strip()[:2000] or None,
    )
    user.billing_country = bc
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, None


def cancel_payment_claim(db: Session, user: models.User, claim_id: int) -> str | None:
    row = (
        db.query(models.PaymentClaim)
        .filter(
            models.PaymentClaim.id == int(claim_id),
            models.PaymentClaim.user_id == int(user.id),
        )
        .first()
    )
    if not row:
        return "신청을 찾을 수 없습니다."
    if row.status != CLAIM_STATUS_PENDING:
        return "대기 중인 신청만 취소할 수 있습니다."
    row.status = CLAIM_STATUS_CANCELLED
    row.updated_at = datetime.utcnow()
    db.commit()
    return None


def confirm_payment_claim(
    db: Session,
    claim_id: int,
    admin_user: models.User,
    *,
    admin_note: str = "",
    period_days: int = 31,
) -> str | None:
    row = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
    if not row:
        return "신청을 찾을 수 없습니다."
    if row.status != CLAIM_STATUS_PENDING:
        return "이미 처리된 신청입니다."
    user = db.query(models.User).filter(models.User.id == row.user_id).first()
    if not user:
        return "회원을 찾을 수 없습니다."
    now = datetime.utcnow()
    end = now + timedelta(days=max(1, int(period_days)))
    user.subscription_plan_code = row.plan_code
    user.subscription_plan_source = SUBSCRIPTION_SOURCE_ADMIN
    user.subscription_plan_expires_at = end
    user.billing_country = row.billing_country
    row.status = CLAIM_STATUS_CONFIRMED
    row.confirmed_at = now
    row.confirmed_by_user_id = int(admin_user.id)
    row.subscription_period_start = now
    row.subscription_period_end = end
    row.admin_note = (admin_note or "").strip()[:2000] or row.admin_note
    row.updated_at = now
    db.commit()
    return None


def reject_payment_claim(
    db: Session,
    claim_id: int,
    admin_user: models.User,
    *,
    admin_note: str = "",
) -> str | None:
    row = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
    if not row:
        return "신청을 찾을 수 없습니다."
    if row.status != CLAIM_STATUS_PENDING:
        return "대기 중인 신청만 반려할 수 있습니다."
    row.status = CLAIM_STATUS_REJECTED
    row.admin_note = (admin_note or "").strip()[:2000] or None
    row.updated_at = datetime.utcnow()
    db.commit()
    return None


def claims_for_user(db: Session, user_id: int, limit: int = 20) -> list[models.PaymentClaim]:
    return (
        db.query(models.PaymentClaim)
        .filter(models.PaymentClaim.user_id == int(user_id))
        .order_by(models.PaymentClaim.created_at.desc())
        .limit(limit)
        .all()
    )


def pending_claims_for_admin(db: Session, limit: int = 100) -> list[models.PaymentClaim]:
    return (
        db.query(models.PaymentClaim)
        .filter(models.PaymentClaim.status == CLAIM_STATUS_PENDING)
        .order_by(models.PaymentClaim.created_at.asc())
        .limit(limit)
        .all()
    )


def claim_status_label_ko(status: str) -> str:
    return {
        CLAIM_STATUS_PENDING: "확인 대기",
        CLAIM_STATUS_CONFIRMED: "활성화 완료",
        CLAIM_STATUS_REJECTED: "반려",
        CLAIM_STATUS_CANCELLED: "취소",
    }.get(status, status)
