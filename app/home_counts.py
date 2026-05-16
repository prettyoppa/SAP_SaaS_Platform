"""홈 타일용 회원별 진행 건수(단순 5단계)."""

from __future__ import annotations

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, joinedload

from . import models
from .menu_landing import abap_analysis_menu_bucket, integration_menu_bucket
from .request_hub_access import abap_analysis_consultant_read_scope
from .rfp_landing import BUCKET_ORDER, rfp_landing_bucket


def home_tile_counts(
    db: Session, user_id: int, *, is_admin: bool = False, consultant_matched: bool = False
) -> dict:
    """
    각 메뉴별 건수 키 (모두 동일한 라벨):

    delivery — 납품 (FS·납품 코드 ready 또는 생성 중)
    proposal — 개발 제안서 생성됨
    analysis — 분석 단계(중간 상태)
    in_progress — 진행 중
    draft — 임시저장

    is_admin이면 각 메뉴의 집계는 전체 사용자 기준(홈 타일 제목 옆 “전체 N”용).
    """
    uid = user_id

    rfp_q = db.query(models.RFP).options(joinedload(models.RFP.messages))
    if is_admin:
        pass
    elif consultant_matched:
        ro = models.RequestOffer
        rfp_q = rfp_q.filter(
            or_(
                models.RFP.user_id == uid,
                exists().where(
                    ro.request_kind == "rfp",
                    ro.request_id == models.RFP.id,
                    ro.consultant_user_id == uid,
                    ro.status == "matched",
                ),
            )
        )
    else:
        rfp_q = rfp_q.filter(models.RFP.user_id == uid)
    rfps = rfp_q.all()

    r_counts = {k: 0 for k in BUCKET_ORDER}
    for r in rfps:
        b = rfp_landing_bucket(r)
        if b in r_counts:
            r_counts[b] += 1

    a_q = db.query(models.AbapAnalysisRequest).options(
        joinedload(models.AbapAnalysisRequest.workflow_rfp).joinedload(models.RFP.messages)
    )
    if is_admin:
        pass
    elif consultant_matched:
        a_q = a_q.filter(
            or_(
                models.AbapAnalysisRequest.user_id == uid,
                abap_analysis_consultant_read_scope(uid),
            )
        )
    else:
        a_q = a_q.filter(models.AbapAnalysisRequest.user_id == uid)
    analyses = a_q.all()

    a_delivery = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "delivery")
    a_proposal = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "proposal")
    a_analysis = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "analysis")
    a_in_progress = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "in_progress")
    a_draft = sum(1 for a in analyses if abap_analysis_menu_bucket(a) == "draft")

    ir_q = db.query(models.IntegrationRequest).options(
        joinedload(models.IntegrationRequest.interview_messages),
        joinedload(models.IntegrationRequest.workflow_rfp).joinedload(models.RFP.messages),
    )
    if is_admin:
        pass
    elif consultant_matched:
        ro = models.RequestOffer
        ir_q = ir_q.filter(
            or_(
                models.IntegrationRequest.user_id == uid,
                exists().where(
                    ro.request_kind == "integration",
                    ro.request_id == models.IntegrationRequest.id,
                    ro.consultant_user_id == uid,
                    ro.status == "matched",
                ),
            )
        )
    else:
        ir_q = ir_q.filter(models.IntegrationRequest.user_id == uid)
    integrations = ir_q.all()

    ir_delivery = sum(1 for ir in integrations if integration_menu_bucket(ir) == "delivery")
    ir_proposal = sum(1 for ir in integrations if integration_menu_bucket(ir) == "proposal")
    ir_analysis = sum(1 for ir in integrations if integration_menu_bucket(ir) == "analysis")
    ir_in_progress = sum(1 for ir in integrations if integration_menu_bucket(ir) == "in_progress")
    ir_draft = sum(1 for ir in integrations if integration_menu_bucket(ir) == "draft")

    return {
        "rfp": {
            "delivery": r_counts["delivery"],
            "proposal": r_counts["proposal"],
            "analysis": r_counts["analysis"],
            "in_progress": r_counts["in_progress"],
            "draft": r_counts["draft"],
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
