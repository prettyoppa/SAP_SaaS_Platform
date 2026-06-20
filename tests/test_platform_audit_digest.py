"""회원 주요 이벤트 digest."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app import models
from app.platform_audit import (
    EVENT_MEMBER_REGISTERED,
    EVENT_WALLET_TOPUP_SUBMITTED,
    record_event,
    should_record_actor,
)
from app.platform_audit_digest import (
    SETTING_LAST_EVENT_ID,
    _set_setting,
    build_digest_email_body,
    build_digest_sms_body,
    group_events_by_actor,
    run_audit_digest,
)


def _evt(email: str, event_type: str, *, eid: int = 1) -> models.PlatformAuditEvent:
    return models.PlatformAuditEvent(
        id=eid,
        actor_user_id=1,
        actor_email=email,
        event_type=event_type,
        created_at=datetime(2026, 5, 29, 10, 0, 0),
    )


class PlatformAuditRecordTests(unittest.TestCase):
    def test_skip_admin_and_test_accounts(self):
        admin = models.User(id=1, email="a@x.com", hashed_password="x", is_admin=True)
        test = models.User(id=2, email="t@x.com", hashed_password="x", is_test_account=True)
        member = models.User(id=3, email="m@x.com", hashed_password="x")
        self.assertFalse(should_record_actor(admin))
        self.assertFalse(should_record_actor(test))
        self.assertTrue(should_record_actor(member))

    def test_record_event_skips_admin(self):
        db = MagicMock()
        admin = models.User(id=1, email="a@x.com", hashed_password="x", is_admin=True)
        record_event(db, admin, EVENT_MEMBER_REGISTERED)
        db.add.assert_not_called()


class PlatformAuditDigestTests(unittest.TestCase):
    def test_group_events_by_actor(self):
        events = [
            _evt("b@x.com", EVENT_WALLET_TOPUP_SUBMITTED, eid=1),
            _evt("a@x.com", EVENT_MEMBER_REGISTERED, eid=2),
            _evt("a@x.com", EVENT_WALLET_TOPUP_SUBMITTED, eid=3),
        ]
        grouped = group_events_by_actor(events)
        self.assertEqual(list(grouped.keys()), ["b@x.com", "a@x.com"])
        self.assertEqual(len(grouped["a@x.com"]), 2)

    def test_build_digest_email_body(self):
        body = build_digest_email_body([_evt("m@x.com", EVENT_MEMBER_REGISTERED)])
        self.assertIn("m@x.com", body)
        self.assertIn("회원가입", body)

    def test_build_digest_sms_body_truncates(self):
        events = [_evt(f"user{i}@x.com", EVENT_MEMBER_REGISTERED, eid=i) for i in range(20)]
        body = build_digest_sms_body(events)
        self.assertIn("[회원이벤트]", body)
        self.assertLessEqual(len(body), 900)

    @patch("app.platform_audit_digest._set_setting")
    @patch("app.platform_audit_digest._effective_last_event_id", return_value=0)
    @patch("app.platform_audit_digest._notify_admins_sms")
    @patch("app.platform_audit_digest._notify_admins_email")
    @patch("app.platform_audit_digest.pending_events")
    @patch("app.platform_audit_digest.digest_sms_enabled", return_value=False)
    @patch("app.platform_audit_digest.digest_email_enabled", return_value=True)
    def test_run_digest_commits_watermark_before_email(
        self, _email_on, _sms_on, mock_pending, mock_email, mock_sms, _after_id, mock_set
    ):
        db = MagicMock()
        evt = _evt("m@x.com", EVENT_MEMBER_REGISTERED)
        evt.id = 42
        mock_pending.return_value = [evt]
        n = run_audit_digest(db)
        self.assertEqual(n, 1)
        mock_email.assert_called_once()
        mock_sms.assert_not_called()
        db.commit.assert_called_once()
        id_updates = [c for c in mock_set.call_args_list if c[0][1] == SETTING_LAST_EVENT_ID]
        self.assertTrue(id_updates)
        self.assertEqual(id_updates[-1][0][2], "42")

    def test_set_setting_creates_missing_row(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        _set_setting(db, SETTING_LAST_EVENT_ID, "99")
        db.add.assert_called_once()
        row = db.add.call_args[0][0]
        self.assertEqual(row.key, SETTING_LAST_EVENT_ID)
        self.assertEqual(row.value, "99")

    @patch("app.platform_audit_digest.pending_events")
    @patch("app.platform_audit_digest.digest_sms_enabled", return_value=False)
    @patch("app.platform_audit_digest.digest_email_enabled", return_value=False)
    def test_run_digest_disabled(self, _email_on, _sms_on, mock_pending):
        db = MagicMock()
        n = run_audit_digest(db)
        self.assertEqual(n, 0)
        mock_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
