"""PortOne 체크아웃 — 회원 통화·거래 통화에 따른 채널/금액."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from .. import models
from ..billing_currency import user_prefers_usd_payments
from ..ai_wallet import usd_krw_rate_from_db
from .portone_settings import portone_channel_key, portone_paypal_channel_key

_log = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class PortoneCheckoutParams:
    channel_key: str
    checkout_mode: str  # card | paypal
    checkout_currency: str  # CURRENCY_KRW | CURRENCY_USD
    checkout_amount: int  # KRW won or USD cents
    use_paypal: bool
    paypal_channel_configured: bool
    paypal_unavailable_for_usd: bool


def _krw_to_usd_cents(amount_krw: int, rate: float) -> int:
    r = rate if rate > 0 else 1350.0
    return max(1, int(round((int(amount_krw) / r) * 100)))


def resolve_portone_checkout(
    user: models.User,
    txn: models.PaymentTransaction,
    db: Session,
    *,
    paypal_query_override: bool = False,
) -> PortoneCheckoutParams:
    """Payment currency USD → PayPal(USD). KRW → 국내 카드(KRW). ?pay=paypal 은 QA용."""
    paypal_key = portone_paypal_channel_key()
    card_key = portone_channel_key()
    wants_paypal = bool(paypal_key) and (
        user_prefers_usd_payments(user) or paypal_query_override
    )
    txn_currency = (txn.currency or "KRW").strip().upper()
    amount_minor = int(txn.amount_minor or 0)

    if not wants_paypal:
        return PortoneCheckoutParams(
            channel_key=card_key,
            checkout_mode="card",
            checkout_currency="CURRENCY_KRW",
            checkout_amount=amount_minor,
            use_paypal=False,
            paypal_channel_configured=bool(paypal_key),
            paypal_unavailable_for_usd=False,
        )

    if not paypal_key:
        return PortoneCheckoutParams(
            channel_key=card_key,
            checkout_mode="card",
            checkout_currency="CURRENCY_KRW",
            checkout_amount=amount_minor,
            use_paypal=False,
            paypal_channel_configured=False,
            paypal_unavailable_for_usd=user_prefers_usd_payments(user),
        )

    if txn_currency == "USD":
        return PortoneCheckoutParams(
            channel_key=paypal_key,
            checkout_mode="paypal",
            checkout_currency="CURRENCY_USD",
            checkout_amount=max(1, amount_minor),
            use_paypal=True,
            paypal_channel_configured=True,
            paypal_unavailable_for_usd=False,
        )

    rate = float(usd_krw_rate_from_db(db) or 1350.0)
    try:
        usd_cents = _krw_to_usd_cents(amount_minor, rate)
    except Exception:
        _log.exception("paypal amount conversion failed txn_id=%s", txn.id)
        usd_cents = 100
    return PortoneCheckoutParams(
        channel_key=paypal_key,
        checkout_mode="paypal",
        checkout_currency="CURRENCY_USD",
        checkout_amount=usd_cents,
        use_paypal=True,
        paypal_channel_configured=True,
        paypal_unavailable_for_usd=False,
    )
