"""목록 단계 타일 — 최종 구현은 ZIP 등록 후에만 활성."""

from unittest.mock import MagicMock

from app.rfp_phase_gates import abap_analysis_phase_gates, integration_phase_gates, rfp_phase_gates


def _rfp(**kw):
    r = MagicMock()
    r.id = 14
    r.user_id = 1
    r.status = "submitted"
    r.interview_status = "completed"
    r.proposal_text = "# prop"
    r.workflow_origin = "direct"
    r.messages = []
    r.delivered_code_status = kw.get("delivered_code_status", "ready")
    r.delivered_code_text = kw.get("delivered_code_text", "# abap")
    r.delivered_code_payload = kw.get("delivered_code_payload", None)
    r.reference_code_payload = None
    r.as_built_zip_json = kw.get("as_built_zip_json", None)
    r.fs_status = "ready"
    r.fs_text = "# fs"
    return r


def test_as_built_tile_inactive_when_only_dev_code():
    rfp = _rfp()
    ph = rfp_phase_gates(rfp, user=None, db=None)
    assert ph["has_dev_code"] is True
    assert ph["has_as_built"] is False
    assert ph["as_built_href"] is None


def test_as_built_tile_active_when_zip_registered():
    rfp = _rfp(as_built_zip_json='{"path":"/x.zip","filename":"x.zip"}')
    ph = rfp_phase_gates(rfp, user=None, db=None)
    assert ph["has_as_built"] is True
    assert ph["as_built_href"] is not None


def test_integration_as_built_requires_zip():
    ir = MagicMock()
    ir.id = 2
    ir.user_id = 1
    ir.status = "submitted"
    ir.interview_status = "completed"
    ir.proposal_text = "p"
    ir.interview_messages = []
    ir.delivered_code_status = "ready"
    ir.reference_code_payload = None
    ir.as_built_zip_json = None
    ir.fs_status = "ready"
    ir.fs_text = "fs"
    ph = integration_phase_gates(ir, user=None, db=None)
    assert ph["has_dev_code"] is True
    assert ph["has_as_built"] is False


def test_abap_draft_shows_request_phase_link():
    row = MagicMock()
    row.id = 6
    row.user_id = 1
    row.is_draft = True
    row.is_analyzed = False
    row.delivered_code_status = "none"
    row.as_built_zip_json = None
    row.fs_status = "none"
    row.fs_text = ""
    row.proposal_text = ""
    row.interview_status = ""
    ph = abap_analysis_phase_gates(row, user=None)
    assert ph["request_href"] == "/abap-analysis/6/edit"


def test_abap_as_built_requires_zip():
    row = MagicMock()
    row.id = 3
    row.user_id = 1
    row.is_draft = False
    row.is_analyzed = True
    row.delivered_code_status = "ready"
    row.as_built_zip_json = None
    row.fs_status = "ready"
    row.fs_text = "fs"
    row.proposal_text = "p"
    row.interview_status = "completed"
    ph = abap_analysis_phase_gates(row, user=None)
    assert ph["has_dev_code"] is True
    assert ph["has_as_built"] is False
