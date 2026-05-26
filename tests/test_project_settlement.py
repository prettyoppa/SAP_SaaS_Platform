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
    r.requester_amount_agreed_at = kw.get("requester_amount_agreed_at", None)
    r.consultant_amount_agreed_at = kw.get("consultant_amount_agreed_at", None)
    return r


def test_open_without_agreement():
    assert recompute_status(_row()) == STATUS_OPEN


def test_awaiting_payment_when_agreed_on_platform():
    r = _row(
        gross_amount_krw=1_000_000,
        use_platform_payment=True,
        requester_amount_agreed_at=datetime.utcnow(),
        consultant_amount_agreed_at=datetime.utcnow(),
    )
    assert recompute_status(r) == STATUS_AWAITING_PAYMENT


def test_funded_without_delivery_confirm():
    r = _row(
        funded_at=datetime.utcnow(),
        gross_amount_krw=1_000_000,
        use_platform_payment=True,
        requester_amount_agreed_at=datetime.utcnow(),
        consultant_amount_agreed_at=datetime.utcnow(),
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
