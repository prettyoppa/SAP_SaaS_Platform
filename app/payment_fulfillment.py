"""PortOne 결제 완료 후 목적별 반영."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from . import models
from .ai_wallet import apply_wallet_credit, apply_wallet_debit
from .payment_purpose import PURPOSE_AI_WALLET_TOPUP, PURPOSE_PROJECT_SETTLEMENT
from .project_settlement import STATUS_AWAITING_PAYMENT, STATUS_FUNDED, mark_funded, mark_unfunded

_log = logging.getLogger("uvicorn.error")

TXN_STATUS_PENDING = "pending"
TXN_STATUS_PAID = "paid"
TXN_STATUS_FAILED = "failed"
TXN_STATUS_CANCELLED = "cancelled"


def fulfill_paid_transaction(db: Session, txn: models.PaymentTransaction) -> str | None:
    """이미 paid면 None. 실패 시 에러 코드 문자열."""
    if (txn.status or "") == TXN_STATUS_PAID:
        return None
    purpose = (txn.purpose or "").strip()
    if purpose == PURPOSE_AI_WALLET_TOPUP:
        return _fulfill_wallet_topup(db, txn)
    if purpose == PURPOSE_PROJECT_SETTLEMENT:
        return _fulfill_project_settlement(db, txn)
    return "unknown_purpose"


def _fulfill_wallet_topup(db: Session, txn: models.PaymentTransaction) -> str | None:
    from .ai_wallet import usd_krw_rate_from_db

    user = db.query(models.User).filter(models.User.id == int(txn.user_id)).first()
    if not user:
        return "user_not_found"
    amt = int(txn.amount_minor or 0)
    if amt <= 0:
        return "invalid_amount"
    if (txn.currency or "KRW").strip().upper() == "USD":
        rate = float(usd_krw_rate_from_db(db) or 1350.0)
        credit_krw = max(1, int(round((amt / 100.0) * rate)))
    else:
        credit_krw = amt
    apply_wallet_credit(user, credit_krw)
    txn.status = TXN_STATUS_PAID
    db.add(user)
    db.add(txn)
    return None


def _fulfill_project_settlement(db: Session, txn: models.PaymentTransaction) -> str | None:
    sid = int(txn.purpose_ref_id or 0)
    settlement = db.query(models.ProjectSettlement).filter(models.ProjectSettlement.id == sid).first()
    if not settlement:
        return "settlement_not_found"
    if int(settlement.owner_user_id) != int(txn.user_id):
        return "forbidden"
    if settlement.status != STATUS_AWAITING_PAYMENT:
        if settlement.funded_at:
            txn.status = TXN_STATUS_PAID
            db.add(txn)
            return None
        return "not_awaiting_payment"
    expected = int(settlement.gross_amount_krw or 0)
    paid = int(txn.amount_minor or 0)
    txn_cur = (txn.currency or "KRW").strip().upper()
    if txn_cur == "USD":
        from .ai_wallet import usd_krw_rate_from_db
        from .payment_providers.portone_checkout import _krw_to_usd_cents

        rate = float(usd_krw_rate_from_db(db) or 1350.0)
        expected_usd = _krw_to_usd_cents(expected, rate)
        if abs(paid - expected_usd) > 1:
            return "amount_mismatch"
    elif expected != paid:
        return "amount_mismatch"
    mark_funded(db, settlement, portone_payment_id=(txn.payment_id or "")[:256])
    txn.status = TXN_STATUS_PAID
    db.add(txn)
    return None


def reverse_paid_transaction(db: Session, txn: models.PaymentTransaction) -> str | None:
    """PG 취소·환불 시 paid 반영을 되돌림. 이미 cancelled면 None."""
    if (txn.status or "") == TXN_STATUS_CANCELLED:
        return None
    if (txn.status or "") != TXN_STATUS_PAID:
        txn.status = TXN_STATUS_CANCELLED
        db.add(txn)
        return None
    purpose = (txn.purpose or "").strip()
    if purpose == PURPOSE_AI_WALLET_TOPUP:
        return _reverse_wallet_topup(db, txn)
    if purpose == PURPOSE_PROJECT_SETTLEMENT:
        return _reverse_project_settlement(db, txn)
    txn.status = TXN_STATUS_CANCELLED
    db.add(txn)
    return "unknown_purpose"


def _reverse_wallet_topup(db: Session, txn: models.PaymentTransaction) -> str | None:
    from .ai_wallet import usd_krw_rate_from_db

    user = db.query(models.User).filter(models.User.id == int(txn.user_id)).first()
    if not user:
        return "user_not_found"
    amt = int(txn.amount_minor or 0)
    if amt <= 0:
        return "invalid_amount"
    if (txn.currency or "KRW").strip().upper() == "USD":
        rate = float(usd_krw_rate_from_db(db) or 1350.0)
        debit_krw = max(1, int(round((amt / 100.0) * rate)))
    else:
        debit_krw = amt
    apply_wallet_debit(user, debit_krw)
    txn.status = TXN_STATUS_CANCELLED
    db.add(user)
    db.add(txn)
    return None


def _reverse_project_settlement(db: Session, txn: models.PaymentTransaction) -> str | None:
    sid = int(txn.purpose_ref_id or 0)
    settlement = db.query(models.ProjectSettlement).filter(models.ProjectSettlement.id == sid).first()
    if not settlement:
        return "settlement_not_found"
    if (settlement.status or "") not in (STATUS_FUNDED, STATUS_AWAITING_PAYMENT):
        _log.warning(
            "portone cancel skipped settlement status=%s id=%s",
            settlement.status,
            settlement.id,
        )
        txn.status = TXN_STATUS_CANCELLED
        db.add(txn)
        return "settlement_not_reversible"
    if not mark_unfunded(db, settlement):
        return "settlement_not_reversible"
    txn.status = TXN_STATUS_CANCELLED
    db.add(txn)
    return None
