"""홈 타일용 회원별 진행 건수(단순 5단계)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models
from .menu_landing import abap_analysis_menu_bucket, integration_menu_bucket


def home_tile_counts(db: Session, user_id: int, *, is_admin: bool = False) -> dict:
    """
    각 메뉴별 건수 키 (모두 동일한 라벨):

    delivery — 납품 (향후 FS~납품 구간, 현재 0)
    proposal — 개발 제안서 생성됨
    analysis — 분석 단계(중간 상태)
    in_progress — 진행 중
    draft — 임시저장

    is_admin이면 각 메뉴의 집계는 전체 사용자 기준(홈 타일 제목 옆 “전체 N”용).
    """
    uid = user_id

    rfp_q = db.query(models.RFP)
    if not is_admin:
        rfp_q = rfp_q.filter(models.RFP.user_id == uid)
    rfps = rfp_q.all()

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

    a_q = db.query(models.AbapAnalysisRequest)
    if not is_admin:
        a_q = a_q.filter(models.AbapAnalysisRequest.user_id == uid)
    analyses = a_q.all()

    a_delivery = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "delivery")
    a_proposal = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "proposal")
    a_analysis = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "analysis")
    a_in_progress = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "in_progress")
    a_draft = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "draft")

    ir_q = db.query(models.IntegrationRequest)
    if not is_admin:
        ir_q = ir_q.filter(models.IntegrationRequest.user_id == uid)
    integrations = ir_q.all()

    ir_delivery = sum(1 for ir in integrations if integration_menu_bucket(ir) == "delivery")
    ir_proposal = sum(1 for ir in integrations if integration_menu_bucket(ir) == "proposal")
    ir_analysis = sum(1 for ir in integrations if integration_menu_bucket(ir) == "analysis")
    ir_in_progress = sum(1 for ir in integrations if integration_menu_bucket(ir) == "in_progress")
    ir_draft = sum(1 for ir in integrations if integration_menu_bucket(ir) == "draft")

    return {
        "rfp": {
            "delivery": r_delivery,
            "proposal": r_proposal,
            "analysis": r_analysis,
            "in_progress": r_in_progress,
            "draft": r_draft,
        },
        "rfp_total": len(rfps),
        "abap_analysis": {
            "delivery": a_delivery,
            "proposal": a_proposal,
            "analysis": a_analysis,
            "in_progress": a_in_progress,
            "draft": a_draft,
        },
        "abap_analysis_total": len(analyses),
        "integration": {
            "delivery": ir_delivery,
            "proposal": ir_proposal,
            "analysis": ir_analysis,
            "in_progress": ir_in_progress,
            "draft": ir_draft,
        },
        "integration_total": len(integrations),
    }
