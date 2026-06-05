"""납품 대금 알림."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app import models
from app.project_settlement_notifications import (
    notify_admins_settlement_bank_claim_submitted,
    notify_admins_settlement_funded_online,
    notify_consultant_settlement_bank_claim_submitted,
    notify_consultant_settlement_funded,
    notify_member_settlement_bank_confirmed,
)


def _settlement(**kw) -> models.ProjectSettlement:
    return models.ProjectSettlement(
        id=kw.get("id", 7),
        request_kind=kw.get("request_kind", "rfp"),
        request_id=kw.get("request_id", 100),
        request_offer_id=1,
        owner_user_id=1,
        consultant_user_id=2,
        status="awaiting_payment",
        gross_amount_krw=kw.get("gross_amount_krw", 500_000),
        consultant_payout_krw=kw.get("consultant_payout_krw", 450_000),
        funded_at=kw.get("funded_at"),
    )


def _claim(**kw) -> models.PaymentClaim:
    return models.PaymentClaim(
        id=kw.get("id", 55),
        user_id=1,
        status="pending",
        billing_country="KR",
        currency="KRW",
        amount_minor=500_000,
        plan_account_kind="member",
        plan_code="project_settlement",
        billing_period="project",
        depositor_name="홍길동",
        project_settlement_id=7,
    )


class ProjectSettlementNotifyTests(unittest.TestCase):
    @patch("app.project_settlement_notifications.send_offer_inquiry_sms")
    @patch("app.project_settlement_notifications.send_plain_notification_email")
    @patch("app.project_settlement_notifications._notify_admins")
    def test_bank_submitted_notifies_admin_and_consultant(self, mock_admin, mock_email, mock_sms):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(title="테스트 RFP")
        owner = models.User(id=1, email="owner@test.com", full_name="의뢰자", hashed_password="x")
        consultant = models.User(
            id=2,
            email="con@test.com",
            full_name="컨설턴트",
            hashed_password="x",
            ops_email_opt_in=True,
            ops_sms_opt_in=True,
            phone_verified=True,
            phone_number="+821011111111",
        )
        settlement = _settlement()
        claim = _claim()
        notify_admins_settlement_bank_claim_submitted(db, claim, settlement, owner, consultant)
        notify_consultant_settlement_bank_claim_submitted(db, claim, settlement, owner, consultant)
        admin_body = mock_admin.call_args.kwargs["email_body"]
        self.assertIn("owner@test.com", admin_body)
        self.assertIn("con@test.com", admin_body)
        self.assertIn("의뢰자 계정:", admin_body)
        mock_admin.assert_called_once()
        mock_email.assert_called_once()
        mock_sms.assert_called_once()

    @patch("app.project_settlement_notifications.send_offer_inquiry_sms")
    @patch("app.project_settlement_notifications.send_plain_notification_email")
    @patch("app.project_settlement_notifications._notify_admins")
    def test_portone_funded_notifies_admin_and_consultant(self, mock_admin, mock_email, mock_sms):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(title="테스트 RFP")
        owner = models.User(id=1, email="owner@test.com", full_name="의뢰자", hashed_password="x")
        consultant = models.User(
            id=2,
            email="con@test.com",
            full_name="컨설턴트",
            hashed_password="x",
            ops_email_opt_in=True,
        )
        settlement = _settlement(funded_at=datetime.utcnow())
        notify_consultant_settlement_funded(db, settlement, owner, consultant, source="portone")
        notify_admins_settlement_funded_online(db, settlement, owner, consultant)
        mock_admin.assert_called_once()
        mock_email.assert_called_once()
        mock_sms.assert_not_called()

    @patch("app.project_settlement_notifications.send_offer_inquiry_sms")
    @patch("app.project_settlement_notifications.send_plain_notification_email")
    def test_consultant_without_ops_skips_channels(self, mock_email, mock_sms):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(title="테스트 RFP")
        owner = models.User(id=1, email="owner@test.com", full_name="의뢰자", hashed_password="x")
        consultant = models.User(
            id=2,
            email="con@test.com",
            full_name="컨설턴트",
            hashed_password="x",
            ops_email_opt_in=False,
            ops_sms_opt_in=False,
            phone_verified=False,
        )
        settlement = _settlement()
        claim = _claim()
        notify_consultant_settlement_bank_claim_submitted(db, claim, settlement, owner, consultant)
        mock_email.assert_not_called()
        mock_sms.assert_not_called()

    @patch("app.project_settlement_notifications.send_offer_inquiry_sms")
    @patch("app.project_settlement_notifications.send_plain_notification_email")
    def test_member_notified_on_bank_confirm_without_admin_identity(self, mock_email, mock_sms):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(title="테스트 RFP")
        owner = models.User(
            id=1,
            email="owner@test.com",
            full_name="의뢰자",
            hashed_password="x",
            phone_verified=True,
            phone_number="+821022222222",
        )
        settlement = _settlement()
        claim = _claim()
        claim.status = "confirmed"
        claim.confirmed_amount_minor = 500_000
        notify_member_settlement_bank_confirmed(db, claim, settlement, owner)
        mock_email.assert_called_once()
        body = mock_email.call_args[0][2]
        self.assertIn("관리자", body)
        self.assertNotIn("admin@", body.lower())
        self.assertIn("500,000", body)
        mock_sms.assert_called_once()
        sms = mock_sms.call_args[0][1]
        self.assertIn("관리자", sms)


if __name__ == "__main__":
    unittest.main()
