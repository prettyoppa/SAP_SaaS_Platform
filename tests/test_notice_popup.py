"""홈 공지 팝업 조회."""

from unittest.mock import MagicMock

from app.notice_popup import (
    HOME_POPUP_NOTICE_LIMIT,
    get_home_popup_notice,
    get_home_popup_notices,
)


def _notice(*, id, sort_order=0, active=True, popup=False):
    n = MagicMock()
    n.id = id
    n.sort_order = sort_order
    n.is_active = active
    n.show_home_popup = popup
    return n


def test_get_home_popup_notice_filters_and_orders():
    db = MagicMock()
    chain = db.query.return_value.filter.return_value.order_by.return_value
    chain.first.return_value = _notice(id=2, sort_order=0, popup=True)
    row = get_home_popup_notice(db)
    assert row is not None
    assert int(row.id) == 2
    db.query.assert_called_once()


def test_get_home_popup_notices_returns_up_to_two():
    db = MagicMock()
    chain = db.query.return_value.filter.return_value.order_by.return_value
    chain.limit.return_value.all.return_value = [
        _notice(id=1, sort_order=0, popup=True),
        _notice(id=2, sort_order=1, popup=True),
    ]
    rows = get_home_popup_notices(db)
    assert len(rows) == 2
    assert int(rows[0].id) == 1
    assert int(rows[1].id) == 2
    chain.limit.assert_called_once_with(HOME_POPUP_NOTICE_LIMIT)


def test_get_home_popup_notices_empty_when_limit_zero():
    db = MagicMock()
    rows = get_home_popup_notices(db, limit=0)
    assert rows == []
    db.query.assert_not_called()
