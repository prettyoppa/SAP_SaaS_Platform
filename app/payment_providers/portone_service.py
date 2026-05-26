"""PortOne V2 — 결제 동기화·웹훅."""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..payment_fulfillment import (
    TXN_STATUS_CANCELLED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PAID,
    TXN_STATUS_PENDING,
    fulfill_paid_transaction,
    reverse_paid_transaction,
)
from ..payment_purpose import PURPOSE_AI_WALLET_TOPUP, PURPOSE_PROJECT_SETTLEMENT
from .portone_settings import portone_api_secret, portone_checkout_ready

_log = logging.getLogger("uvicorn.error")


def _payment_client():
    secret = portone_api_secret()
    if not secret:
        raise RuntimeError("PORTONE_API_SECRET 미설정")
    from portone_server_sdk import PaymentClient

    return PaymentClient(secret=secret)


def new_payment_id(*, purpose: str, purpose_ref_id: int) -> str:
    return f"pt-{purpose}-{int(purpose_ref_id)}-{uuid.uuid4().hex[:12]}"


def create_pending_transaction(
    db: Session,
    user: models.User,
    *,
    purpose: str,
    purpose_ref_id: int,
    amount_krw: int,
    return_url: str,
    cancel_url: str = "",
) -> models.PaymentTransaction | None:
    if not portone_checkout_ready():
        return None
    amt = int(amount_krw)
    if amt <= 0:
        return None
    pid = new_payment_id(purpose=purpose, purpose_ref_id=purpose_ref_id)
    row = models.PaymentTransaction(
        user_id=int(user.id),
        purpose=purpose.strip()[:32],
        purpose_ref_id=int(purpose_ref_id),
        payment_id=pid[:128],
        amount_minor=amt,
        currency="KRW",
        provider="portone",
        status=TXN_STATUS_PENDING,
        return_url=(return_url or "")[:1024],
        cancel_url=(cancel_url or "")[:1024] or None,
    )
    db.add(row)
    db.flush()
    return row


def _payment_is_paid(actual: Any) -> bool:
    try:
        from portone_server_sdk._generated.payment.paid_payment import PaidPayment

        return isinstance(actual, PaidPayment)
    except Exception:
        cls = type(actual).__name__
        return cls == "PaidPayment" or (cls.endswith("PaidPayment"))


def _payment_is_cancelled(actual: Any) -> bool:
    try:
        from portone_server_sdk._generated.payment.cancelled_payment import CancelledPayment

        return isinstance(actual, CancelledPayment)
    except Exception:
        cls = type(actual).__name__
        return cls == "CancelledPayment" or ("Cancelled" in cls and "Paid" not in cls)


def _paid_amount_krw(actual: Any) -> int | None:
    try:
        amt = getattr(actual, "amount", None)
        if amt is None:
            return None
        total = getattr(amt, "total", None)
        if total is not None:
            return int(total)
    except (TypeError, ValueError):
        pass
    return None


def sync_payment(db: Session, payment_id: str) -> models.PaymentTransaction | None:
    """PortOne API 조회 후 paid면 fulfill, cancelled면 paid 반영 되돌림."""
    pid = (payment_id or "").strip()
    if not pid:
        return None
    txn = (
        db.query(models.PaymentTransaction)
        .filter(models.PaymentTransaction.payment_id == pid)
        .first()
    )
    if not txn:
        return None
    if (txn.status or "") == TXN_STATUS_CANCELLED:
        return txn
    try:
        client = _payment_client()
        actual = client.get_payment(payment_id=pid)
    except Exception:
        _log.exception("portone get_payment failed payment_id=%s", pid)
        return txn

    if _payment_is_cancelled(actual):
        if (txn.status or "") == TXN_STATUS_PAID:
            err = reverse_paid_transaction(db, txn)
            if err:
                _log.warning("portone reverse failed payment_id=%s err=%s", pid, err)
        elif (txn.status or "") == TXN_STATUS_PENDING:
            txn.status = TXN_STATUS_CANCELLED
            db.add(txn)
        db.commit()
        db.refresh(txn)
        return txn

    if not _payment_is_paid(actual):
        return txn

    if (txn.status or "") == TXN_STATUS_PAID:
        return txn

    paid_amt = _paid_amount_krw(actual)
    if paid_amt is not None and paid_amt != int(txn.amount_minor or 0):
        _log.warning(
            "portone amount mismatch payment_id=%s expected=%s got=%s",
            pid,
            txn.amount_minor,
            paid_amt,
        )
        txn.status = TXN_STATUS_FAILED
        db.add(txn)
        db.commit()
        return txn
    err = fulfill_paid_transaction(db, txn)
    if err:
        _log.warning("portone fulfill failed payment_id=%s err=%s", pid, err)
    else:
        from datetime import datetime

        txn.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(txn)
    return txn


def verify_webhook(payload: str, headers: dict[str, str]) -> Any:
    from .portone_settings import portone_webhook_secret

    import portone_server_sdk as portone

    secret = portone_webhook_secret()
    if not secret:
        raise RuntimeError("PORTONE_WEBHOOK_SECRET 미설정")
    return portone.webhook.verify(secret, payload, headers)


def webhook_payment_id(webhook: Any) -> str | None:
    try:
        import portone_server_sdk as portone

        paid_types = (portone.webhook.WebhookTransactionPaid,)
        cancel_names = (
            "WebhookTransactionCancelled",
            "WebhookTransactionCancelledCancelled",
            "WebhookTransactionCancelledCancelPending",
            "WebhookTransactionCancelledPartialCancelled",
        )
        cancel_types = tuple(
            getattr(portone.webhook, name)
            for name in cancel_names
            if hasattr(portone.webhook, name)
        )
        for cls in paid_types + cancel_types:
            if isinstance(webhook, cls):
                return str(webhook.data.payment_id)
    except Exception:
        pass
    if isinstance(webhook, dict):
        typ = str(webhook.get("type") or "")
        if "Transaction" in typ and any(k in typ for k in ("Paid", "Cancelled", "Cancel")):
            data = webhook.get("data") or {}
            if isinstance(data, dict):
                if data.get("paymentId"):
                    return str(data["paymentId"])
                if data.get("payment_id"):
                    return str(data["payment_id"])
        data = webhook.get("data") or {}
        if isinstance(data, dict) and data.get("paymentId"):
            return str(data["paymentId"])
        if data.get("payment_id"):
            return str(data["payment_id"])
    data = getattr(webhook, "data", None)
    if data is not None:
        pid = getattr(data, "payment_id", None)
        if pid:
            return str(pid)
    return None


def sync_user_portone_transactions(
    db: Session,
    user_id: int,
    *,
    purpose: str | None = None,
    limit: int = 10,
) -> None:
    """paid·pending PortOne 건을 PG 상태와 재동기화(취소 반영·웹훅 누락 보정)."""
    q = (
        db.query(models.PaymentTransaction)
        .filter(
            models.PaymentTransaction.user_id == int(user_id),
            models.PaymentTransaction.provider == "portone",
            models.PaymentTransaction.status.in_([TXN_STATUS_PAID, TXN_STATUS_PENDING]),
        )
        .order_by(models.PaymentTransaction.updated_at.desc(), models.PaymentTransaction.id.desc())
    )
    if purpose:
        q = q.filter(models.PaymentTransaction.purpose == purpose.strip()[:32])
    for txn in q.limit(max(1, int(limit))).all():
        pid = (txn.payment_id or "").strip()
        if pid:
            try:
                sync_payment(db, pid)
            except Exception:
                _log.exception("portone user sync failed payment_id=%s", pid)


def order_name_for_transaction(txn: models.PaymentTransaction) -> str:
    if txn.purpose == PURPOSE_PROJECT_SETTLEMENT:
        return f"납품 대금 #{txn.purpose_ref_id}"
    if txn.purpose == PURPOSE_AI_WALLET_TOPUP:
        return "AI 크레딧 충전"
    return "결제"
