"""홈 타일용 회원별 진행 건수(단순 5단계)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


def home_tile_counts(db: Session, user_id: int) -> dict:
    """
    각 메뉴별 건수 키 (모두 동일한 라벨):

    delivery — 납품 (향후 FS~납품 구간, 현재 0)
    proposal — 개발 제안서 생성됨
    analysis — 분석 단계(중간 상태)
    in_progress — 진행 중
    draft — 임시저장
    """
    uid = user_id

    rfps = db.query(models.RFP).filter(models.RFP.user_id == uid).all()

    def _has_prop(r: models.RFP) -> bool:
        return bool((r.proposal_text or "").strip())

    r_delivery = 0  # 추후 반영
    r_proposal = sum(1 for r in rfps if _has_prop(r))
    r_analysis = sum(
        1 for r in rfps if (r.interview_status or "") == "generating_proposal" and not _has_prop(r)
    )
    r_in_progress = sum(
        1
        for r in rfps
        if (r.status or "") != "draft"
        and not _has_prop(r)
        and (r.interview_status or "") in ("pending", "in_progress")
    )
    r_draft = sum(1 for r in rfps if (r.status or "") == "draft")

    analyses = (
        db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.user_id == uid).all()
    )

    a_delivery = 0
    a_proposal = 0  # 이 메뉴 제안 기능 미연동
    a_analysis = sum(1 for a in analyses if not a.is_draft and not a.is_analyzed)
    a_in_progress = sum(1 for a in analyses if not a.is_draft and a.is_analyzed)
    a_draft = sum(1 for a in analyses if a.is_draft)

    integrations = (
        db.query(models.IntegrationRequest).filter(models.IntegrationRequest.user_id == uid).all()
    )

    # 연동: 상태 분류 로직 추후 — 타일 반영만
    ir_delivery = 0
    ir_proposal = sum(1 for ir in integrations if (ir.proposal_text or "").strip())
    ir_analysis = 0
    ir_in_progress = 0
    ir_draft = 0

    return {
        "rfp": {
            "delivery": r_delivery,
            "proposal": r_proposal,
            "analysis": r_analysis,
            "in_progress": r_in_progress,
            "draft": r_draft,
        },
        "abap_analysis": {
            "delivery": a_delivery,
            "proposal": a_proposal,
            "analysis": a_analysis,
            "in_progress": a_in_progress,
            "draft": a_draft,
        },
        "integration": {
            "delivery": ir_delivery,
            "proposal": ir_proposal,
            "analysis": ir_analysis,
            "in_progress": ir_in_progress,
            "draft": ir_draft,
        },
    }
