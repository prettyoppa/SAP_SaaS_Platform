"""분석·개선 — 제출 후 요청 수정 잠금."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.abap_analysis_request_edit import (
    abap_hub_request_edit_unlocked,
    abap_may_open_request_edit_form,
)


def _row(**kw):
    return SimpleNamespace(**kw)


def _user(uid=1):
    return SimpleNamespace(id=uid, is_admin=False)


def test_draft_always_editable():
    db = MagicMock()
    row = _row(user_id=1, is_draft=True, interview_status="pending", proposal_text=None)
    assert abap_may_open_request_edit_form(db, row, _user(1)) is True


def test_submitted_unlocked_without_proposal():
    db = MagicMock()
    row = _row(
        user_id=1,
        is_draft=False,
        interview_status="pending",
        proposal_text=None,
        workflow_rfp_id=None,
        workflow_rfp=None,
    )
    assert abap_hub_request_edit_unlocked(db, row) is True
    assert abap_may_open_request_edit_form(db, row, _user(1)) is True


def test_locked_when_proposal_exists():
    db = MagicMock()
    row = _row(
        user_id=1,
        is_draft=False,
        interview_status="completed",
        proposal_text="# Proposal",
        workflow_rfp_id=None,
        workflow_rfp=None,
    )
    assert abap_hub_request_edit_unlocked(db, row) is False


def test_unlocked_after_proposal_deleted():
    db = MagicMock()
    row = _row(
        user_id=1,
        is_draft=False,
        interview_status="completed",
        proposal_text="",
        workflow_rfp_id=None,
        workflow_rfp=None,
    )
    assert abap_hub_request_edit_unlocked(db, row) is True
