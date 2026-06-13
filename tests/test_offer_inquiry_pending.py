"""오퍼 문의 답변 대기 — 배치 조회."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.offer_inquiry_service import (
    _any_pending_inquiry_reply_batch,
    _pending_inquiry_reply_offer_ids_batch,
)


def _inq(author_user_id: int):
    row = MagicMock()
    row.author_user_id = author_user_id
    return row


@patch("app.offer_inquiry_service.inquiries_by_offer_id")
def test_pending_reply_offer_ids_batch(mock_inquiries):
    db = MagicMock()
    mock_inquiries.return_value = {
        1: [_inq(10)],
        2: [_inq(20)],
        3: [],
    }
    out = _pending_inquiry_reply_offer_ids_batch(db, [(1, 20), (2, 20), (3, 20)])
    assert out == {1}
    mock_inquiries.assert_called_once_with(db, [1, 2, 3])


@patch("app.offer_inquiry_service.inquiries_by_offer_id")
def test_any_pending_reply_stops_at_first(mock_inquiries):
    db = MagicMock()
    mock_inquiries.return_value = {5: [_inq(99)]}
    assert _any_pending_inquiry_reply_batch(db, [(5, 42)]) is True
    assert _any_pending_inquiry_reply_batch(db, [(5, 99)]) is False
    assert _any_pending_inquiry_reply_batch(db, []) is False
