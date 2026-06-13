"""RFP 랜딩 버킷 — interview 메시지 배치 힌트."""

from types import SimpleNamespace

from app.rfp_landing import rfp_landing_bucket


def _rfp(**kwargs):
    defaults = {
        "fs_status": "none",
        "delivered_code_status": "none",
        "proposal_text": None,
        "status": "submitted",
        "fs_text": None,
        "delivered_code_payload": None,
        "delivered_code_text": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_proposal_ignores_interview_flag():
    r = _rfp(proposal_text="yes")
    assert rfp_landing_bucket(r, has_interview_messages=False) == "proposal"


def test_analysis_when_interview_hint():
    r = _rfp()
    assert rfp_landing_bucket(r, has_interview_messages=True) == "analysis"
    assert rfp_landing_bucket(r, has_interview_messages=False) == "in_progress"
