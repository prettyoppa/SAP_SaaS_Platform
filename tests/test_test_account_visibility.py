"""테스트 계정 소유 요청 — 비테스트 뷰어 조회 제외."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.test_account_visibility import (
    block_test_owned_for_viewer,
    viewer_hides_test_owned_requests,
)


def _user(**kw):
    return SimpleNamespace(**kw)


def test_admin_and_test_viewers_see_test_requests():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (1,)
    assert viewer_hides_test_owned_requests(_user(is_admin=True)) is False
    assert viewer_hides_test_owned_requests(_user(is_test_account=True)) is False
    assert block_test_owned_for_viewer(db, _user(is_admin=True), 99) is False
    assert block_test_owned_for_viewer(db, _user(is_test_account=True), 99) is False


def test_regular_consultant_blocked_from_test_owner():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (1,)
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True)
    assert viewer_hides_test_owned_requests(viewer) is True
    assert block_test_owned_for_viewer(db, viewer, 42) is True


def test_regular_consultant_sees_non_test_owner():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True)
    assert block_test_owned_for_viewer(db, viewer, 42) is False
