"""Consultant-controlled requester visibility for FS and dev code."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.request_deliverables_release import (
    dev_code_withheld_from_requester,
    fs_withheld_from_requester,
    on_dev_code_generation_succeeded,
    on_fs_generation_succeeded,
    user_can_view_dev_code_deliverable_content,
    user_can_view_fs_deliverable_content,
)
from app.request_hub_access import apply_hub_deliverables_visibility


def _entity(*, fs_ready=False, dc_ready=False, fs_vis=False, dc_vis=False):
    return SimpleNamespace(
        fs_status="ready" if fs_ready else "none",
        fs_text="fs body" if fs_ready else "",
        delivered_code_status="ready" if dc_ready else "none",
        delivered_code_text="legacy" if dc_ready else "",
        delivered_code_payload='{"slots":[{"filename":"a.abap","body":"x"}]}' if dc_ready else None,
        fs_visible_to_requester=fs_vis,
        dev_code_visible_to_requester=dc_vis,
    )


def test_owner_cannot_view_ready_fs_until_released():
    db = MagicMock()
    owner = SimpleNamespace(id=1, is_admin=False, is_consultant=False)
    ent = _entity(fs_ready=True, fs_vis=False)
    assert not user_can_view_fs_deliverable_content(
        db, owner, request_kind="rfp", request_id=9, owner_user_id=1, entity=ent
    )
    assert fs_withheld_from_requester(owner, owner_user_id=1, entity=ent)


def test_owner_can_view_fs_after_consultant_release():
    db = MagicMock()
    owner = SimpleNamespace(id=1, is_admin=False, is_consultant=False)
    ent = _entity(fs_ready=True, fs_vis=True)
    assert user_can_view_fs_deliverable_content(
        db, owner, request_kind="rfp", request_id=9, owner_user_id=1, entity=ent
    )
    assert not fs_withheld_from_requester(owner, owner_user_id=1, entity=ent)


@patch("app.request_deliverables_release.consultant_is_matched_on_request", return_value=True)
def test_matched_consultant_always_views_ready_deliverables(_matched):
    db = MagicMock()
    consultant = SimpleNamespace(id=2, is_admin=False, is_consultant=True)
    ent = _entity(fs_ready=True, dc_ready=True, fs_vis=False, dc_vis=False)
    assert user_can_view_fs_deliverable_content(
        db, consultant, request_kind="rfp", request_id=9, owner_user_id=1, entity=ent
    )
    assert user_can_view_dev_code_deliverable_content(
        db, consultant, request_kind="rfp", request_id=9, owner_user_id=1, entity=ent
    )


def test_generation_resets_requester_visibility():
    ent = SimpleNamespace(fs_visible_to_requester=True, dev_code_visible_to_requester=True)
    on_fs_generation_succeeded(ent)
    on_dev_code_generation_succeeded(ent)
    assert ent.fs_visible_to_requester is False
    assert ent.dev_code_visible_to_requester is False


@patch("app.request_hub_access.user_can_operate_request_deliverables", return_value=False)
@patch("app.request_hub_access.user_can_view_request_deliverables", return_value=True)
def test_masks_fs_only_when_withheld_from_owner(_shell, _operate):
    ctx = {"fs_html": "<p>fs</p>", "delivered_package": {"slots": []}, "ana_has_delivered_zip": True}
    owner = SimpleNamespace(id=1, is_admin=False, is_consultant=False)
    ent = _entity(fs_ready=True, dc_ready=True, fs_vis=False, dc_vis=True)
    apply_hub_deliverables_visibility(
        ctx,
        db=MagicMock(),
        user=owner,
        request_kind="analysis",
        request_id=1,
        owner_user_id=1,
        paid_entity=ent,
    )
    assert ctx["fs_withheld_from_requester"] is True
    assert ctx["fs_html"] == ""
    assert ctx["delivered_package"] == {"slots": []}
