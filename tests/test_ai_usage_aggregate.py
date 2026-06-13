"""AiUsageEvent 집계 — SQL SUM, 페이지 로드용."""

from datetime import datetime
from unittest.mock import MagicMock

from app.ai_usage_recorder import sum_usage_usd_micro_for_user


def test_sum_usage_usd_micro_for_user_uses_sql_sum():
    db = MagicMock()
    filt = db.query.return_value.filter.return_value
    filt.scalar.return_value = 1_500_000
    total = sum_usage_usd_micro_for_user(db, 7)
    assert total == 1_500_000
    db.query.assert_called_once()
