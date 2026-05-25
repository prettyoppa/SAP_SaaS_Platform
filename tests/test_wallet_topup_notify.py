"""AI 충전·가입 알림."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app import models
from app.wallet_topup_notifications import (
    notify_admins_new_registration,
    notify_admins_wallet_topup_submitted,
    notify_member_wallet_topup_reviewed,
)


class WalletTopupNotifyTests(unittest.TestCase):
    @patch("app.wallet_topup_notifications.send_offer_inquiry_sms")
    @patch("app.wallet_topup_notifications.send_plain_notification_email")
    def test_notify_admins_on_topup_submitted(self, mock_email, mock_sms):
        db = MagicMock()
        admin = models.User(
            id=9,
            email="admin@test.com",
            full_name="Admin User",
            hashed_password="x",
            is_admin=True,
            is_active=True,
            ops_email_opt_in=True,
            ops_sms_opt_in=False,
            phone_verified=False,
        )
        db.query.return_value.filter.return_value.all.return_value = [admin]
        member = models.User(id=1, email="m@test.com", full_name="홍길동", hashed_password="x")
        claim = models.PaymentClaim(
            id=42,
            user_id=1,
            status="pending",
            billing_country="KR",
            currency="KRW",
            amount_minor=30000,
            plan_account_kind="member",
            plan_code="ai_wallet_topup",
            billing_period="topup",
            depositor_name="홍길동",
        )
        notify_admins_wallet_topup_submitted(db, claim, member)
        mock_email.assert_called_once()
        subject, body = mock_email.call_args[0][1], mock_email.call_args[0][2]
        self.assertIn("충전 신청", subject)
        self.assertIn("홍길동", body)
        self.assertIn("30,000", body)
        mock_sms.assert_not_called()

    @patch("app.wallet_topup_notifications.send_offer_inquiry_sms")
    @patch("app.wallet_topup_notifications.send_plain_notification_email")
    def test_notify_admins_on_topup_submitted_sms_when_phone_verified(self, mock_email, mock_sms):
        db = MagicMock()
        admin = models.User(
            id=9,
            email="admin@test.com",
            full_name="Admin User",
            hashed_password="x",
            is_admin=True,
            is_active=True,
            phone_number="+821011112222",
            phone_verified=True,
        )
        db.query.return_value.filter.return_value.all.return_value = [admin]
        member = models.User(id=1, email="m@test.com", full_name="홍길동", hashed_password="x")
        claim = models.PaymentClaim(
            id=42,
            user_id=1,
            status="pending",
            billing_country="KR",
            currency="KRW",
            amount_minor=30000,
            plan_account_kind="member",
            plan_code="ai_wallet_topup",
            billing_period="topup",
            depositor_name="홍길동",
        )
        notify_admins_wallet_topup_submitted(db, claim, member)
        mock_email.assert_called_once()
        mock_sms.assert_called_once()
        self.assertEqual(mock_sms.call_args[0][0], "+821011112222")
        self.assertEqual(mock_sms.call_args[1].get("sms_type"), "wallet_topup_admin")

    @patch("app.wallet_topup_notifications.send_offer_inquiry_sms")
    @patch("app.wallet_topup_notifications.send_plain_notification_email")
    def test_notify_member_on_confirm(self, mock_email, mock_sms):
        member = models.User(
            id=1,
            email="m@test.com",
            full_name="홍길동",
            hashed_password="x",
            ops_email_opt_in=True,
            ops_sms_opt_in=True,
            phone_verified=True,
            phone_number="+821011111111",
        )
        claim = models.PaymentClaim(
            id=42,
            user_id=1,
            status="confirmed",
            billing_country="KR",
            currency="KRW",
            amount_minor=10000,
            plan_account_kind="member",
            plan_code="ai_wallet_topup",
            billing_period="topup",
            depositor_name="홍길동",
            confirmed_amount_minor=5000,
        )
        notify_member_wallet_topup_reviewed(MagicMock(), claim, member, action="confirmed")
        mock_email.assert_called_once()
        body = mock_email.call_args[0][2]
        self.assertIn("관리자", body)
        self.assertNotIn("Admin User", body)
        self.assertIn("5,000", body)
        self.assertIn("10,000", body)
        mock_sms.assert_called_once()

    @patch("app.wallet_topup_notifications.send_offer_inquiry_sms")
    @patch("app.wallet_topup_notifications.send_plain_notification_email")
    def test_notify_member_on_reject(self, mock_email, mock_sms):
        member = models.User(
            id=1,
            email="m@test.com",
            full_name="홍길동",
            hashed_password="x",
            ops_email_opt_in=True,
        )
        claim = models.PaymentClaim(
            id=42,
            user_id=1,
            status="rejected",
            billing_country="KR",
            currency="KRW",
            amount_minor=10000,
            plan_account_kind="member",
            plan_code="ai_wallet_topup",
            billing_period="topup",
            depositor_name="홍길동",
            confirmed_amount_minor=0,
        )
        notify_member_wallet_topup_reviewed(MagicMock(), claim, member, action="rejected")
        body = mock_email.call_args[0][2]
        self.assertIn("반려", body)
        self.assertIn("0", body)

    @patch("app.wallet_topup_notifications.send_offer_inquiry_sms")
    @patch("app.wallet_topup_notifications.send_plain_notification_email")
    def test_notify_admins_on_register(self, mock_email, mock_sms):
        db = MagicMock()
        admin = models.User(
            id=9,
            email="admin@test.com",
            full_name="Admin",
            hashed_password="x",
            is_admin=True,
            is_active=True,
            phone_number="+821011111111",
            phone_verified=True,
        )
        db.query.return_value.filter.return_value.all.return_value = [admin]
        user = models.User(
            id=2,
            email="new@test.com",
            full_name="신규",
            hashed_password="x",
            consultant_application_pending=True,
        )
        notify_admins_new_registration(db, user)
        mock_email.assert_called_once()
        subject, body = mock_email.call_args[0][1], mock_email.call_args[0][2]
        self.assertIn("신규 회원 가입", subject)
        self.assertIn("가입회원 이름: 신규", body)
        self.assertIn("이메일 주소: new@test.com", body)
        self.assertIn("컨설턴트", body)
        mock_sms.assert_called_once()
        sms_body = mock_sms.call_args[0][1]
        self.assertIn("신규", sms_body)
        self.assertIn("new@test.com", sms_body)


if __name__ == "__main__":
    unittest.main()
