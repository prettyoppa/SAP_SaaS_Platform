"""계좌이체 입금 신청·Admin 확인."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .ai_wallet import (
    MIN_TOPUP_KRW,
    WALLET_TOPUP_PLAN_CODE,
    apply_wallet_credit,
    apply_wallet_debit,
    is_wallet_topup_plan_code,
)
from .payment_claim_messages import (
    ERR_AMOUNT_MISMATCH,
    ERR_AMOUNT_TOO_LOW,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_PENDING,
    ERR_DEPOSITOR_REQUIRED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_COUNTRY,
    ERR_KRW_AMOUNT_MISSING,
    ERR_PENDING_CLAIM_EXISTS,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_REQUIRED,
    ERR_USD_AMOUNT_MISSING,
)
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
        return None, ERR_PLAN_NOT_FOUND
    krw, usd_cents = resolve_plan_monthly_prices(row)
    if billing_country == "KR":
        if krw is None or krw <= 0:
            return None, ERR_KRW_AMOUNT_MISSING
        return int(krw), None
    if billing_country == "US":
        if usd_cents is None or usd_cents <= 0:
            return None, ERR_USD_AMOUNT_MISSING
        return int(usd_cents), None
    return None, ERR_INVALID_COUNTRY


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


def create_wallet_topup_claim(
    db: Session,
    user: models.User,
    *,
    amount_minor: int,
    depositor_name: str,
    transfer_date: datetime | None,
    member_note: str = "",
) -> tuple[models.PaymentClaim | None, str | None]:
    """원화 계좌이체 AI 잔액 충전 신청 (한국만)."""
    try:
        amt = int(amount_minor)
    except (TypeError, ValueError):
        return None, ERR_INVALID_AMOUNT
    if amt < MIN_TOPUP_KRW:
        return None, ERR_AMOUNT_TOO_LOW
    if user_pending_claim(db, user.id):
        return None, ERR_PENDING_CLAIM_EXISTS
    dep = (depositor_name or "").strip()[:200]
    if not dep:
        return None, ERR_DEPOSITOR_REQUIRED
    kind = account_kind_for_user(user)
    row = models.PaymentClaim(
        user_id=int(user.id),
        status=CLAIM_STATUS_PENDING,
        billing_country="KR",
        currency="KRW",
        amount_minor=amt,
        plan_account_kind=kind,
        plan_code=WALLET_TOPUP_PLAN_CODE,
        billing_period="topup",
        depositor_name=dep,
        transfer_date=transfer_date,
        member_note=(member_note or "").strip()[:2000] or None,
    )
    user.billing_country = "KR"
    row.wallet_credited_on_submit = True
    db.add(row)
    apply_wallet_credit(user, amt)
    db.commit()
    db.refresh(row)
    return row, None


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
        return None, ERR_INVALID_COUNTRY
    currency = "KRW" if bc == "KR" else "USD"
    kind = account_kind_for_user(user)
    code = (plan_code or "").strip()[:32]
    if not code:
        return None, ERR_PLAN_REQUIRED
    expected, err = expected_amount_minor(db, account_kind=kind, plan_code=code, billing_country=bc)
    if err:
        return None, err
    if int(amount_minor) != int(expected):
        return None, f"{ERR_AMOUNT_MISMATCH}:{int(expected)}"
    if user_pending_claim(db, user.id):
        return None, ERR_PENDING_CLAIM_EXISTS
    dep = (depositor_name or "").strip()[:200]
    if not dep:
        return None, ERR_DEPOSITOR_REQUIRED
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
        return ERR_CLAIM_NOT_FOUND
    if row.status != CLAIM_STATUS_PENDING:
        return ERR_CLAIM_NOT_PENDING
    if is_wallet_topup_plan_code(row.plan_code) and bool(row.wallet_credited_on_submit):
        apply_wallet_debit(user, int(row.amount_minor))
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
    if is_wallet_topup_plan_code(row.plan_code):
        if not bool(row.wallet_credited_on_submit):
            apply_wallet_credit(user, int(row.amount_minor))
        user.billing_country = row.billing_country or user.billing_country
    else:
        user.subscription_plan_code = row.plan_code
        user.subscription_plan_source = SUBSCRIPTION_SOURCE_ADMIN
        user.subscription_plan_expires_at = end
        user.billing_country = row.billing_country
        row.subscription_period_start = now
        row.subscription_period_end = end
    row.status = CLAIM_STATUS_CONFIRMED
    row.confirmed_at = now
    row.confirmed_by_user_id = int(admin_user.id)
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
        return ERR_CLAIM_NOT_FOUND
    if row.status != CLAIM_STATUS_PENDING:
        return ERR_CLAIM_NOT_PENDING
    user = db.query(models.User).filter(models.User.id == row.user_id).first()
    if user and is_wallet_topup_plan_code(row.plan_code) and bool(row.wallet_credited_on_submit):
        apply_wallet_debit(user, int(row.amount_minor))
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
    from .payment_claim_messages import STATUS_LABEL_KO

    return STATUS_LABEL_KO.get(status, status)


def claim_status_label_en(status: str) -> str:
    from .payment_claim_messages import STATUS_LABEL_EN

    return STATUS_LABEL_EN.get(status, status)
