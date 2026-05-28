from unittest.mock import MagicMock, patch

from app.payment_providers.portone_checkout import resolve_portone_checkout


def _user(currency="KRW"):
    u = MagicMock()
    u.billing_currency = currency
    return u


def _txn(amount=30000, currency="KRW"):
    t = MagicMock()
    t.id = 1
    t.amount_minor = amount
    t.currency = currency
    return t


@patch("app.payment_providers.portone_checkout.portone_paypal_channel_key", return_value="paypal-key")
@patch("app.payment_providers.portone_checkout.portone_channel_key", return_value="inicis-key")
def test_usd_user_uses_paypal_with_usd_cents_txn(_card, _paypal):
    checkout = resolve_portone_checkout(_user("USD"), _txn(2500, "USD"), MagicMock())
    assert checkout.use_paypal is True
    assert checkout.checkout_mode == "paypal"
    assert checkout.checkout_currency == "CURRENCY_USD"
    assert checkout.checkout_amount == 2500


@patch("app.payment_providers.portone_checkout.portone_paypal_channel_key", return_value="paypal-key")
@patch("app.payment_providers.portone_checkout.portone_channel_key", return_value="inicis-key")
@patch("app.payment_providers.portone_checkout.usd_krw_rate_from_db", return_value=1350.0)
def test_usd_user_krw_txn_converts(_rate, _card, _paypal):
    checkout = resolve_portone_checkout(_user("USD"), _txn(13500, "KRW"), MagicMock())
    assert checkout.use_paypal is True
    assert checkout.checkout_amount == 1000  # $10.00


@patch("app.payment_providers.portone_checkout.portone_paypal_channel_key", return_value="")
@patch("app.payment_providers.portone_checkout.portone_channel_key", return_value="inicis-key")
def test_usd_user_without_paypal_key_falls_back_krw(_card, _paypal):
    checkout = resolve_portone_checkout(_user("USD"), _txn(10000, "KRW"), MagicMock())
    assert checkout.use_paypal is False
    assert checkout.paypal_unavailable_for_usd is True
    assert checkout.checkout_currency == "CURRENCY_KRW"
