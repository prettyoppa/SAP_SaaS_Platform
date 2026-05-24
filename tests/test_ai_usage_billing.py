"""납품 AI — 요청자가 아닌 실행자에게 차감."""

from unittest.mock import MagicMock, patch

from app.ai_usage_billing import (
    delivery_job_billing_user_id,
    skips_delivery_wallet_preflight,
    wallet_preflight_for_delivery_stage,
)


def test_delivery_billing_user_is_actor_not_owner():
    assert delivery_job_billing_user_id(99) == 99


def test_admin_skips_wallet_preflight():
    admin = MagicMock(is_admin=True, is_consultant=False)
    assert skips_delivery_wallet_preflight(admin) is True
    assert wallet_preflight_for_delivery_stage(MagicMock(), admin, stage="fs") is None


def test_consultant_zero_balance_blocked():
    db = MagicMock()
    consultant = MagicMock(is_admin=False, is_consultant=True)
    consultant.ai_wallet_balance_krw = 0

    with patch("app.ai_usage_pricing.billable_usd_micro", return_value=120_000), patch(
        "app.ai_wallet.usd_krw_rate_from_db", return_value=1350.0
    ), patch("app.ai_wallet.wallet_balance_krw", return_value=0):
        err = wallet_preflight_for_delivery_stage(db, consultant, stage="fs")
    assert err == "wallet_insufficient"
