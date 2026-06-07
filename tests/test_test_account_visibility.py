"""테스트 계정 소유 요청 — 비테스트 뷰어 조회 제외."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.test_account_visibility import (
    block_test_owned_for_viewer,
    is_published_to_consultants,
    parse_console_sel_key,
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
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True, id=7)
    assert viewer_hides_test_owned_requests(viewer) is True
    assert block_test_owned_for_viewer(db, viewer, 42) is True


def test_consultant_with_offer_sees_test_owner_request():
    db = MagicMock()
    # test owner, not published, but consultant has offer
    db.query.return_value.filter.return_value.first.side_effect = [(1,), (99,)]
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True, id=7)
    assert (
        block_test_owned_for_viewer(
            db, viewer, 42, request_kind="rfp", request_id=3
        )
        is False
    )


def test_regular_consultant_sees_non_test_owner():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True)
    assert block_test_owned_for_viewer(db, viewer, 42) is False


def test_published_test_request_visible_to_consultant():
    db = MagicMock()
    # owner is test account
    db.query.return_value.filter.return_value.first.side_effect = [(1,), (99,)]
    viewer = _user(is_admin=False, is_test_account=False, is_consultant=True)
    assert (
        block_test_owned_for_viewer(
            db, viewer, 42, request_kind="rfp", request_id=7
        )
        is False
    )


def test_parse_console_sel_key():
    assert parse_console_sel_key("rfp:12") == ("rfp", 12)
    assert parse_console_sel_key("ana:3") == ("analysis", 3)
    assert parse_console_sel_key("int:9") == ("integration", 9)
    assert parse_console_sel_key("bad") is None


def test_is_published_to_consultants():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (1,)
    assert is_published_to_consultants(db, "rfp", 1) is True
    db.query.return_value.filter.return_value.first.return_value = None
    assert is_published_to_consultants(db, "rfp", 1) is False
