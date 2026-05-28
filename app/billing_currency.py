"""회원 결제 통화 선호 (users.billing_currency)."""

from __future__ import annotations

from . import models


def user_payment_currency(user: models.User | None) -> str:
    raw = (getattr(user, "billing_currency", None) or "KRW").strip().upper()
    return raw if raw in ("KRW", "USD") else "KRW"


def user_prefers_usd_payments(user: models.User | None) -> bool:
    return user_payment_currency(user) == "USD"
