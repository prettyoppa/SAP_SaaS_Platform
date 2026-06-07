"""Hub deliverables visibility — FS·개발코드·최종 구현 산출물 마스킹."""

from unittest.mock import MagicMock, patch

from app.request_hub_access import apply_hub_deliverables_visibility


def _ctx_with_as_built():
    return {
        "ana_fs_html": "<p>fs</p>",
        "as_built_entry_dict": {"path": "/r2/x.zip", "filename": "x.zip"},
        "as_built_can_upload": True,
    }


@patch("app.request_hub_access.user_can_operate_request_deliverables", return_value=False)
@patch("app.request_hub_access.user_can_view_request_deliverables", return_value=False)
def test_masks_as_built_when_cannot_view(_view, _operate):
    ctx = _ctx_with_as_built()
    apply_hub_deliverables_visibility(
        ctx,
        db=MagicMock(),
        user=MagicMock(is_consultant=True, is_admin=False, id=99),
        request_kind="analysis",
        request_id=1,
        owner_user_id=2,
        paid_entity=MagicMock(),
    )
    assert ctx["can_view_deliverables"] is False
    assert ctx["as_built_section_visible"] is True
    assert ctx["as_built_entry_dict"] == {}
    assert ctx["as_built_can_upload"] is False
    assert ctx["ana_fs_html"] == ""


@patch("app.request_hub_access.user_can_operate_request_deliverables", return_value=True)
@patch("app.request_hub_access.user_can_view_request_deliverables", return_value=True)
def test_keeps_as_built_when_can_view(_view, _operate):
    ctx = _ctx_with_as_built()
    apply_hub_deliverables_visibility(
        ctx,
        db=MagicMock(),
        user=MagicMock(is_consultant=True, is_admin=False, id=99),
        request_kind="analysis",
        request_id=1,
        owner_user_id=2,
        paid_entity=MagicMock(),
    )
    assert ctx["can_view_deliverables"] is True
    assert ctx["as_built_section_visible"] is True
    assert ctx["as_built_entry_dict"]["path"] == "/r2/x.zip"
    assert ctx["as_built_can_upload"] is True
