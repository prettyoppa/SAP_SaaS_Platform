"""AI 크레딧 — 음수 잔액 방지·선불 검사."""

from unittest.mock import MagicMock, patch

from app.ai_usage_billing import user_skips_wallet, wallet_preflight_for_ai_stage
from app.ai_wallet import (
    apply_wallet_debit,
    debit_wallet_for_usage_micro,
    member_wallet_balance_display_krw,
    wallet_balance_krw,
)


def test_admin_skips_wallet():
    admin = MagicMock(is_admin=True)
    assert user_skips_wallet(admin) is True


def test_member_zero_balance_blocked():
    db = MagicMock()
    member = MagicMock(is_admin=False)
    member.ai_wallet_balance_krw = 0

    with patch("app.ai_usage_pricing.billable_usd_micro", return_value=40_000), patch(
        "app.ai_wallet.usd_krw_rate_from_db", return_value=1350.0
    ):
        err = wallet_preflight_for_ai_stage(db, member, stage="interview")
    assert err == "wallet_insufficient"


def test_member_debit_does_not_go_negative():
    member = MagicMock(is_admin=False)
    member.ai_wallet_balance_krw = 50
    apply_wallet_debit(member, 200)
    assert wallet_balance_krw(member) == 0


def test_member_display_balance_floors_negative():
    member = MagicMock(is_admin=False)
    member.ai_wallet_balance_krw = -117
    assert member_wallet_balance_display_krw(member) == 0


def test_admin_usage_debit_skipped():
    db = MagicMock()
    admin = MagicMock(is_admin=True)
    admin.ai_wallet_balance_krw = 100
    with patch("app.ai_wallet.usd_krw_rate_from_db", return_value=1350.0):
        debited = debit_wallet_for_usage_micro(db, admin, 1_000_000)
    assert debited == 0
    assert wallet_balance_krw(admin) == 100
