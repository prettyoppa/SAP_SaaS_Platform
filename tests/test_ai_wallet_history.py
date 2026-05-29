"""AI wallet top-up history helpers."""

from types import SimpleNamespace

from app.ai_wallet import (
    krw_to_usd_cents,
    portone_txn_credit_krw,
    usd_cents_from_usd_micro,
    wallet_balance_usd_display,
)


def test_portone_txn_credit_krw_usd_cents():
    txn = SimpleNamespace(amount_minor=500, currency="USD")
    assert portone_txn_credit_krw(txn, 1490.0) == 7450


def test_portone_txn_credit_krw_krw():
    txn = SimpleNamespace(amount_minor=30000, currency="KRW")
    assert portone_txn_credit_krw(txn, 1490.0) == 30000


def test_usd_cents_from_usd_micro():
    assert usd_cents_from_usd_micro(1_000_000) == 100  # $1.00


def test_krw_to_usd_cents():
    assert krw_to_usd_cents(7450, 1490.0) == 500


def test_wallet_balance_usd_display():
    assert wallet_balance_usd_display(7450, 1490.0) == 5.0
