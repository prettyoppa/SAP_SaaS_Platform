"""AI inquiry access for offered vs matched consultants."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.request_hub_access import user_may_use_request_ai_inquiry


def test_offered_consultant_may_use_ai_inquiry():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (1,)
    consultant = SimpleNamespace(id=10, is_admin=False, is_consultant=True)
    assert user_may_use_request_ai_inquiry(
        db,
        consultant,
        request_owner_id=1,
        request_kind="rfp",
        request_id=3,
    )


def test_unrelated_consultant_denied():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    consultant = SimpleNamespace(id=10, is_admin=False, is_consultant=True)
    assert not user_may_use_request_ai_inquiry(
        db,
        consultant,
        request_owner_id=1,
        request_kind="rfp",
        request_id=3,
    )
