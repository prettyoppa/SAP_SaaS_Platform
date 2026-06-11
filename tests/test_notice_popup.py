"""홈 공지 팝업 조회."""

from unittest.mock import MagicMock

from app.notice_popup import get_home_popup_notice


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
