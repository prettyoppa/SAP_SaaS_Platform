"""Stripe Checkout 및 웹훅 헬퍼."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import stripe
from sqlalchemy.orm import Session

from . import models
from .paid_tier import PAID_ACTIVE, paid_engagement_is_active

STRIPE_SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
STRIPE_WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"
STRIPE_PRICE_RFP_PAID_ENV = "STRIPE_PRICE_RFP_DEVELOPMENT"


def stripe_keys_configured() -> bool:
    sk = (os.environ.get(STRIPE_SECRET_KEY_ENV) or "").strip()
    price = (os.environ.get(STRIPE_PRICE_RFP_PAID_ENV) or "").strip()
    return bool(sk and price.startswith("price_"))


def configure_stripe() -> None:
    key = (os.environ.get(STRIPE_SECRET_KEY_ENV) or "").strip()
    if key:
        stripe.api_key = key


def get_price_id() -> str | None:
    v = (os.environ.get(STRIPE_PRICE_RFP_PAID_ENV) or "").strip()
    return v or None


def create_rfp_checkout_session(
    *,
    rfp_id: int,
    customer_email: str,
    base_url: str,
) -> Any:
    """Stripe Checkout 세션(one-time payment). 성공 후 billing/confirm 과 웹훅에서 active 처리."""
    configure_stripe()
    price_id = get_price_id()
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_RFP_DEVELOPMENT 미설정")
    origin = base_url.rstrip("/")
    success_url = (
        f"{origin}/rfp/{rfp_id}/billing/confirm?session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{origin}/rfp/{rfp_id}?phase=proposal&checkout=cancelled"
    return stripe.checkout.Session.create(
        mode="payment",
        customer_email=(customer_email or "").strip() or None,
        line_items=[{"price": price_id, "quantity": 1}],
        metadata={"rfp_id": str(rfp_id)},
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


def try_activate_rfp_from_checkout(
    db: Session, session: Any, expect_rfp_id: int | None = None
) -> models.RFP | None:
    """
    Checkout 세션이 결제 완료이고 metadata의 rfp_id가 유효하면 active로 표시합니다.
    idempotent · 이미 active면 조용히 성공 처리.

    billing_confirm 접근에서는 expect_rfp_id 로 URL 과 metadata 일치를 강제합니다.
    """
    raw = getattr(session, "metadata", None)
    meta: dict
    try:
        meta = dict(raw) if raw is not None else {}
    except (TypeError, ValueError):
        meta = {}
        if raw is not None:
            try:
                meta = {k: raw[k] for k in raw}
            except Exception:
                meta = {}
    rid_raw = meta.get("rfp_id")
    try:
        rid = int(rid_raw)
    except (TypeError, ValueError):
        return None
    if expect_rfp_id is not None and rid != int(expect_rfp_id):
        return None
    rfp = db.query(models.RFP).filter(models.RFP.id == rid).first()
    if not rfp:
        return None

    pay_status = (getattr(session, "payment_status", None) or "").strip()
    ses_status = (getattr(session, "status", None) or "").strip()
    if ses_status != "complete":
        return None
    if pay_status not in ("paid", "complete"):
        return None

    if paid_engagement_is_active(rfp):
        return rfp

    rfp.paid_engagement_status = PAID_ACTIVE
    rfp.paid_activated_at = datetime.utcnow()
    sid = getattr(session, "id", None)
    if sid:
        rfp.stripe_checkout_session_id = str(sid)
    db.commit()
    db.refresh(rfp)
    return rfp
