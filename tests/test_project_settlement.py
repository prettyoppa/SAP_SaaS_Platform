"""납품 대금 상태 전이 — AI·개발코드와 무관."""

from datetime import datetime
from unittest.mock import MagicMock

from app.project_settlement import (
    STATUS_AWAITING_PAYMENT,
    STATUS_FUNDED,
    STATUS_OPEN,
    STATUS_PAYABLE,
    STATUS_PAYOUT_COMPLETED,
    recompute_status,
)


def _row(**kw):
    r = MagicMock()
    r.status = kw.get("status", STATUS_OPEN)
    r.payout_completed_at = kw.get("payout_completed_at", None)
    r.funded_at = kw.get("funded_at", None)
    r.requester_delivery_confirmed_at = kw.get("requester_delivery_confirmed_at", None)
    r.consultant_delivery_confirmed_at = kw.get("consultant_delivery_confirmed_at", None)
    r.gross_amount_krw = kw.get("gross_amount_krw", None)
    r.use_platform_payment = kw.get("use_platform_payment", False)
    r.payment_method = kw.get("payment_method", None)
    return r


def test_open_without_payment_terms():
    assert recompute_status(_row()) == STATUS_OPEN


def test_awaiting_payment_when_terms_set_on_platform():
    from app.project_settlement import PAYMENT_METHOD_BANK, PAYMENT_METHOD_PORTONE

    for pm in (PAYMENT_METHOD_BANK, PAYMENT_METHOD_PORTONE, "card"):
        r = _row(
            gross_amount_krw=1_000_000,
            use_platform_payment=True,
            payment_method=pm,
        )
        assert recompute_status(r) == STATUS_AWAITING_PAYMENT


def test_normalize_payment_method_legacy_card():
    from app.project_settlement import PAYMENT_METHOD_PORTONE, normalize_payment_method

    assert normalize_payment_method("card") == PAYMENT_METHOD_PORTONE
    assert normalize_payment_method("portone") == PAYMENT_METHOD_PORTONE


def test_platform_payment_without_method_stays_open():
    r = _row(
        gross_amount_krw=1_000_000,
        use_platform_payment=True,
    )
    assert recompute_status(r) == STATUS_OPEN


def test_funded_without_delivery_confirm():
    r = _row(
        funded_at=datetime.utcnow(),
        gross_amount_krw=1_000_000,
        use_platform_payment=True,
        payment_method="portone",
    )
    assert recompute_status(r) == STATUS_FUNDED


def test_payable_requires_funded_and_both_delivery_confirms():
    r = _row(
        funded_at=datetime.utcnow(),
        requester_delivery_confirmed_at=datetime.utcnow(),
        consultant_delivery_confirmed_at=datetime.utcnow(),
    )
    assert recompute_status(r) == STATUS_PAYABLE


def test_delivery_confirm_alone_not_payable_without_funded():
    r = _row(
        requester_delivery_confirmed_at=datetime.utcnow(),
        consultant_delivery_confirmed_at=datetime.utcnow(),
    )
    assert recompute_status(r) == STATUS_OPEN


def test_payout_completed():
    r = _row(payout_completed_at=datetime.utcnow())
    assert recompute_status(r) == STATUS_PAYOUT_COMPLETED
