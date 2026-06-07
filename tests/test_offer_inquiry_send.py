"""요청자 → 컨설턴트 오퍼 문의 저장·알림."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import models
from app.offer_inquiry_service import inquiry_sender_account_line, send_offer_inquiry_from_owner


def _consultant(*, email_opt: bool = True, sms_opt: bool = False) -> models.User:
    return models.User(
        id=2,
        email="consultant@test.com",
        full_name="Consultant",
        hashed_password="x",
        ops_email_opt_in=email_opt,
        ops_sms_opt_in=sms_opt,
        phone_verified=False,
        phone_number=None,
    )


@patch("app.offer_inquiry_service.send_offer_inquiry_sms")
@patch("app.offer_inquiry_service.send_plain_notification_email")
def test_owner_inquiry_saved_when_email_fails(mock_email, mock_sms):
    mock_email.side_effect = RuntimeError("메일 발송 설정이 없습니다.")
    db = MagicMock()
    row_holder: list[models.RequestOfferInquiry] = []

    def _refresh(obj):
        if isinstance(obj, models.RequestOfferInquiry):
            obj.id = 99
            row_holder.append(obj)

    db.refresh.side_effect = _refresh

    offer = SimpleNamespace(id=6, request_kind="rfp", request_id=14)
    err, row = send_offer_inquiry_from_owner(
        db,
        request=SimpleNamespace(base_url="http://test/"),
        author=SimpleNamespace(id=1, email="owner@test.com", full_name="Owner"),
        offer=offer,
        consultant=_consultant(),
        request_title="Test RFP",
        request_detail_url="http://test/rfp/14",
        body_raw="hello",
    )
    assert row is not None
    assert err is not None
    assert "저장되었으나" in err
    assert db.commit.call_count >= 2
    mock_sms.assert_not_called()


@patch("app.offer_inquiry_service.send_offer_inquiry_sms")
@patch("app.offer_inquiry_service.send_plain_notification_email")
def test_owner_inquiry_ok_when_email_succeeds(mock_email, mock_sms):
    db = MagicMock()

    def _refresh(obj):
        if isinstance(obj, models.RequestOfferInquiry):
            obj.id = 100

    db.refresh.side_effect = _refresh

    offer = SimpleNamespace(id=6, request_kind="rfp", request_id=14)
    err, row = send_offer_inquiry_from_owner(
        db,
        request=SimpleNamespace(base_url="http://test/"),
        author=SimpleNamespace(id=1, email="owner@test.com", full_name="Owner"),
        offer=offer,
        consultant=_consultant(),
        request_title="Test RFP",
        request_detail_url="http://test/rfp/14",
        body_raw="hello",
    )
    assert err is None
    assert row is not None
    mock_email.assert_called_once()


def test_inquiry_sender_account_line_includes_email():
    user = SimpleNamespace(email="user@test.com", full_name="홍길동")
    line = inquiry_sender_account_line(user, role_label="발신(요청자)")
    assert "user@test.com" in line
    assert "홍길동" in line
