"""오퍼 알림: 이메일·SMS 채널 분리 및 요청자 조회."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import models
from app.offer_inquiry_service import (
    _owner_ops_email_channel,
    notify_request_owner_new_console_offer,
)


class OfferNotifyTests(unittest.TestCase):
    def test_owner_ops_email_channel_requires_opt_in_and_address(self):
        owner = SimpleNamespace(ops_email_opt_in=True, email="a@example.com")
        ok, addr = _owner_ops_email_channel(owner)  # type: ignore[arg-type]
        self.assertTrue(ok)
        self.assertEqual(addr, "a@example.com")

        owner2 = SimpleNamespace(ops_email_opt_in=True, email="")
        ok2, _ = _owner_ops_email_channel(owner2)  # type: ignore[arg-type]
        self.assertFalse(ok2)

    @patch("app.offer_inquiry_service.send_offer_inquiry_sms")
    @patch("app.offer_inquiry_service.send_plain_notification_email")
    def test_notify_sends_email_and_sms_independently(
        self, mock_email, mock_sms
    ):
        owner = models.User(
            id=1,
            email="owner@test.com",
            full_name="Owner",
            hashed_password="x",
            ops_email_opt_in=True,
            ops_sms_opt_in=True,
            phone_verified=True,
            phone_number="+821011111111",
        )
        consultant = models.User(
            id=2,
            email="c@test.com",
            full_name="Consultant",
            hashed_password="x",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = owner

        warn = notify_request_owner_new_console_offer(
            db=db,
            request=SimpleNamespace(base_url="http://test/"),
            owner=owner,
            consultant=consultant,
            request_kind="analysis",
            request_id=9,
            request_title="Test request",
        )
        self.assertIsNone(warn)
        mock_email.assert_called_once()
        mock_sms.assert_called_once()
        sms_body = mock_sms.call_args[0][1]
        self.assertNotIn("http://", sms_body)

    @patch("app.offer_inquiry_service.send_offer_inquiry_sms")
    @patch("app.offer_inquiry_service.send_plain_notification_email")
    def test_notify_email_failure_still_attempts_sms(
        self, mock_email, mock_sms
    ):
        mock_email.side_effect = RuntimeError("Resend API 422")
        owner = models.User(
            id=1,
            email="owner@test.com",
            full_name="Owner",
            hashed_password="x",
            ops_email_opt_in=True,
            ops_sms_opt_in=True,
            phone_verified=True,
            phone_number="+821011111111",
        )
        consultant = models.User(
            id=2,
            email="c@test.com",
            full_name="Consultant",
            hashed_password="x",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = owner

        warn = notify_request_owner_new_console_offer(
            db=db,
            request=SimpleNamespace(base_url="http://test/"),
            owner=owner,
            consultant=consultant,
            request_kind="rfp",
            request_id=1,
            request_title="T",
        )
        self.assertIsNotNone(warn)
        self.assertIn("이메일 발송에 실패", warn or "")
        mock_sms.assert_called_once()


if __name__ == "__main__":
    unittest.main()
