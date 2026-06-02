"""분석·개선 — 제출 후 요청 수정 허용·잠금(제안서·연동 신규개발 인터뷰)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


def _workflow_rfp_blocks_request_edit(db: Session, rfp: models.RFP | None) -> bool:
    if not rfp:
        return False
    if (rfp.interview_status or "").strip() == "generating_proposal":
        return True
    if (rfp.proposal_text or "").strip():
        return True
    answered = (
        db.query(models.RFPMessage.id)
        .filter(
            models.RFPMessage.rfp_id == int(rfp.id),
            models.RFPMessage.is_answered.is_(True),
        )
        .first()
    )
    return answered is not None


def abap_hub_request_edit_unlocked(db: Session, row: models.AbapAnalysisRequest) -> bool:
    """True면 상세 허브에서 요청 수정 버튼을 켤 수 있음."""
    if (row.interview_status or "").strip() == "generating_proposal":
        return False
    if (row.proposal_text or "").strip():
        return False
    wf = getattr(row, "workflow_rfp", None)
    if wf is None and getattr(row, "workflow_rfp_id", None):
        wf = db.query(models.RFP).filter(models.RFP.id == int(row.workflow_rfp_id)).first()
    if _workflow_rfp_blocks_request_edit(db, wf):
        return False
    return True


def abap_may_open_request_edit_form(db: Session, row: models.AbapAnalysisRequest, user) -> bool:
    """초안은 항상 허용. 제출 건은 허브와 동일하게 제안·인터뷰(연동 RFP) 전에만 수정 폼."""
    if not row or not user:
        return False
    if int(row.user_id) != int(user.id):
        return False
    if bool(getattr(row, "is_draft", False)):
        return True
    return abap_hub_request_edit_unlocked(db, row)
