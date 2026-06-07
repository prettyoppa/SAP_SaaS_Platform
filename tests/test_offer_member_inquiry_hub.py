"""Tests for hub floating member inquiry panel context."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.offer_member_inquiry_hub import (
    build_offer_member_inquiry_ctx,
    member_inquiry_redirect_url,
)


def _offer(oid: int, *, status: str = "offered", consultant_id: int = 10):
    return SimpleNamespace(
        id=oid,
        status=status,
        consultant_user_id=consultant_id,
        consultant=SimpleNamespace(
            email=f"c{consultant_id}@test.com",
            full_name=f"Consultant {consultant_id}",
        ),
    )


def test_build_ctx_owner_with_active_offers():
    owner = SimpleNamespace(id=1, is_admin=False, is_consultant=False)
    offers = [_offer(1, status="offered"), _offer(2, status="matched", consultant_id=11)]
    ctx = build_offer_member_inquiry_ctx(
        MagicMock(),
        user=owner,
        owner_user_id=1,
        offers=offers,
        inquiries_by_offer_id={},
        can_inquire=True,
        readonly_console=False,
        hub_phase="fs",
        hub_readonly_return_url=None,
        query_params={},
    )
    assert ctx is not None
    assert ctx["mode"] == "owner"
    assert ctx["can_compose"] is True
    assert ctx["default_offer_id"] == 2
    assert ctx["show_offer_picker"] is True


def test_build_ctx_consultant_matched_only():
    consultant = SimpleNamespace(id=10, is_admin=False, is_consultant=True)
    offers = [_offer(1, status="matched", consultant_id=10)]
    ctx = build_offer_member_inquiry_ctx(
        MagicMock(),
        user=consultant,
        owner_user_id=1,
        offers=offers,
        inquiries_by_offer_id={1: [SimpleNamespace()]},
        can_inquire=False,
        readonly_console=False,
        hub_phase="devcode",
        hub_readonly_return_url=None,
        query_params={},
    )
    assert ctx is not None
    assert ctx["mode"] == "consultant"
    assert ctx["show_offer_picker"] is False


def test_build_ctx_owner_hidden_on_readonly_console():
    owner = SimpleNamespace(id=1, is_admin=False, is_consultant=False)
    assert (
        build_offer_member_inquiry_ctx(
            MagicMock(),
            user=owner,
            owner_user_id=1,
            offers=[_offer(1)],
            inquiries_by_offer_id={},
            can_inquire=True,
            readonly_console=True,
            hub_phase="proposal",
            hub_readonly_return_url="/rfp/1/console-readonly?phase=proposal",
            query_params={},
        )
        is None
    )


def test_build_ctx_consultant_shown_on_readonly_console():
    consultant = SimpleNamespace(id=10, is_admin=False, is_consultant=True)
    offers = [_offer(1, status="matched", consultant_id=10)]
    ctx = build_offer_member_inquiry_ctx(
        MagicMock(),
        user=consultant,
        owner_user_id=1,
        offers=offers,
        inquiries_by_offer_id={},
        can_inquire=False,
        readonly_console=True,
        hub_phase="fs",
        hub_readonly_return_url="/rfp/1/console-readonly?phase=fs",
        query_params={},
    )
    assert ctx is not None
    assert ctx["mode"] == "consultant"
    assert ctx["can_compose"] is True


def test_member_inquiry_redirect_preserves_hub_phase():
    url = member_inquiry_redirect_url(
        request_kind="rfp",
        request_id=5,
        hub_phase="fs",
        offer_id=3,
        offer_inquiry_ok="1",
    )
    assert url.startswith("/rfp/5?phase=fs")
    assert "offer_inquiry_ok=1" in url
    assert "offer_inquiry_offer=3" in url
    assert url.endswith("#offer-member-inquiry")


@patch("app.offer_member_inquiry_hub.offer_inquiry_needs_consultant_reply", return_value=True)
def test_build_ctx_consultant_pending_reply(mock_pending):
    consultant = SimpleNamespace(id=10, is_admin=False, is_consultant=True)
    offers = [_offer(1, status="matched", consultant_id=10)]
    ctx = build_offer_member_inquiry_ctx(
        MagicMock(),
        user=consultant,
        owner_user_id=1,
        offers=offers,
        inquiries_by_offer_id={},
        can_inquire=False,
        readonly_console=False,
        hub_phase="proposal",
        hub_readonly_return_url=None,
        query_params={},
    )
    assert ctx["pending_reply"] is True
    mock_pending.assert_called()
