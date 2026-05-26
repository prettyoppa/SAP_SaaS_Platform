"""Stripe Checkout — 납품 대금(동적 금액) 전용."""

from __future__ import annotations

import os
from typing import Any

import stripe
from sqlalchemy.orm import Session

from . import models
from .project_settlement import mark_funded, normalize_request_kind

STRIPE_SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
STRIPE_WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"


def stripe_keys_configured() -> bool:
    return bool((os.environ.get(STRIPE_SECRET_KEY_ENV) or "").strip())


def configure_stripe() -> None:
    key = (os.environ.get(STRIPE_SECRET_KEY_ENV) or "").strip()
    if key:
        stripe.api_key = key


def create_settlement_checkout_session(
    *,
    settlement_id: int,
    request_kind: str,
    request_id: int,
    amount_krw: int,
    customer_email: str,
    base_url: str,
) -> Any:
    configure_stripe()
    if not stripe_keys_configured():
        raise RuntimeError("STRIPE_SECRET_KEY 미설정")
    origin = base_url.rstrip("/")
    kind = normalize_request_kind(request_kind) or "rfp"
    success_url = (
        f"{origin}/settlement/{kind}/{int(request_id)}"
        f"?settlement_ok=card&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{origin}/settlement/{kind}/{int(request_id)}?settlement_err=card_cancelled"
    return stripe.checkout.Session.create(
        mode="payment",
        customer_email=(customer_email or "").strip() or None,
        line_items=[
            {
                "price_data": {
                    "currency": "krw",
                    "unit_amount": int(amount_krw),
                    "product_data": {
                        "name": "납품 대금 (프로젝트)",
                        "description": f"{kind.upper()} #{int(request_id)}",
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={
            "settlement_id": str(int(settlement_id)),
            "request_kind": kind,
            "request_id": str(int(request_id)),
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )


def retrieve_checkout_session(session_id: str) -> Any:
    configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def construct_webhook_event(payload: bytes, sig_header: str | None) -> Any:
    configure_stripe()
    wh_secret = (os.environ.get(STRIPE_WEBHOOK_SECRET_ENV) or "").strip()
    if not wh_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET 미설정")
    if not sig_header:
        raise ValueError("Missing stripe-signature")
    return stripe.Webhook.construct_event(payload, sig_header, wh_secret)


def try_activate_settlement_from_checkout(db: Session, session: Any) -> models.ProjectSettlement | None:
    raw = getattr(session, "metadata", None)
    meta: dict
    try:
        meta = dict(raw) if raw is not None else {}
    except (TypeError, ValueError):
        meta = {}
    sid_raw = meta.get("settlement_id")
    try:
        settlement_id = int(sid_raw)
    except (TypeError, ValueError):
        return None
    row = db.query(models.ProjectSettlement).filter(models.ProjectSettlement.id == settlement_id).first()
    if not row:
        return None
    pay_status = (getattr(session, "payment_status", None) or "").strip()
    ses_status = (getattr(session, "status", None) or "").strip()
    if ses_status != "complete" or pay_status not in ("paid", "complete"):
        return None
    if row.funded_at:
        return row
    stripe_sid = getattr(session, "id", None)
    mark_funded(db, row, stripe_session_id=str(stripe_sid) if stripe_sid else None)
    db.commit()
    db.refresh(row)
    return row
