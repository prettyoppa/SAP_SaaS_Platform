"""RFP 리스트 타일의 단계 버튼(개발코드·FS·제안서·인터뷰·요청) 가용성·링크."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from . import models
from .integration_hub import integration_hub_url
from .request_hub_access import consultant_has_request_offer, menu_abap_detail_url, menu_entity_hub_url
from .paid_tier import PAID_ACTIVE
from .rfp_hub import rfp_hub_url
from .rfp_reference_code import normalize_reference_code_payload


def _reference_code_has_content_json(data: dict[str, Any]) -> bool:
    slots = data.get("slots")
    if not isinstance(slots, list):
        return False
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if (slot.get("program_id") or "").strip() or (slot.get("title") or "").strip():
            return True
        for sec in slot.get("sections") or []:
            if isinstance(sec, dict) and (sec.get("code") or "").strip():
                return True
    return False


def _reference_code_has_content(rfp: models.RFP) -> bool:
    raw = normalize_reference_code_payload(getattr(rfp, "reference_code_payload", None))
    if not raw:
        return False
    try:
        data: dict[str, Any] = json.loads(raw)
    except Exception:
        return False
    return _reference_code_has_content_json(data)


def reference_code_payload_has_content(raw: str | None) -> bool:
    """AbapAnalysisRequest.reference_code_payload 등 RFP 외 레코드용."""
    norm = normalize_reference_code_payload(raw)
    if not norm:
        return False
    try:
        data: dict[str, Any] = json.loads(norm)
    except Exception:
        return False
    return _reference_code_has_content_json(data)


def rfp_phase_gates(rfp: models.RFP, user: Optional[Any] = None) -> dict[str, Any]:
    """
    Jinja 필터용. has_* / href 키는 템플릿에서 사용.
    FS: 결제 완료·FS/납품 파이프라인 시작 후 활성 — **관리자**는 결제 전에도 링크 허브로 진입 가능(납품 콘솔 테스트).
    개발코드 버튼: (1) 고객이 첨부한 참조 ABAP → /rfp/{id}/dev-code
                     (2) 에이전트 납품 ABAP 진행·완료 → /rfp/{id}/fs (같은 허브에서 미리보기·다운로드)
    """
    rid = rfp.id
    owner_id = int(rfp.user_id)
    has_ref_dev = _reference_code_has_content(rfp)

    paid_on = (rfp.paid_engagement_status or "none").strip() == PAID_ACTIVE
    fs_s = (getattr(rfp, "fs_status", None) or "none").strip()
    dc_s = (getattr(rfp, "delivered_code_status", None) or "none").strip()
    pipeline = fs_s != "none" or dc_s != "none"
    is_operator = bool(
        user and (getattr(user, "is_admin", False) or getattr(user, "is_consultant", False))
    )
    has_fs = paid_on or pipeline or is_operator
    fs_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="fs") if has_fs else None

    st = (rfp.status or "").strip()
    iv = (rfp.interview_status or "").strip()
    prop = (rfp.proposal_text or "").strip()
    nmsg = len(getattr(rfp, "messages", None) or [])

    wo = (getattr(rfp, "workflow_origin", None) or "").strip().lower()
    workflow_abap = wo == "abap_analysis"

    has_proposal = bool(prop) or iv == "generating_proposal"
    if workflow_abap and st != "draft":
        has_proposal = True
    if iv == "generating_proposal":
        proposal_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="proposal")
    elif prop:
        proposal_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="proposal")
    elif workflow_abap and st != "draft":
        proposal_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="proposal")
    else:
        proposal_href = None

    has_interview = False
    interview_href: str | None = None
    if not workflow_abap and st != "draft":
        if iv == "generating_proposal":
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="interview", view_summary=True
            )
        elif iv == "in_progress":
            has_interview = True
            interview_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="interview")
        elif iv == "completed":
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="interview", view_summary=True
            )
        elif nmsg > 0:
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="interview", view_summary=True
            )
        elif st == "submitted" and iv == "pending":
            has_interview = True
            interview_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="interview")

    request_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="request")

    dc_started = dc_s != "none"
    if dc_started:
        dev_code_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="devcode")
    elif has_ref_dev:
        dev_code_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="rfp", request_id=rid, phase="devcode")
    else:
        dev_code_href = None

    has_dev_code = dc_started or has_ref_dev

    return {
        "has_dev_code": has_dev_code,
        "dev_code_href": dev_code_href,
        "has_fs": has_fs,
        "fs_href": fs_href,
        "has_proposal": has_proposal,
        "proposal_href": proposal_href,
        "has_interview": has_interview,
        "interview_href": interview_href,
        "request_href": request_href,
    }


def integration_phase_gates(ir: models.IntegrationRequest, user: Optional[Any] = None) -> dict[str, Any]:
    """
    연동 개발(IntegrationRequest) 리스트용 — FS·개발코드·제안·인터뷰는 IR 레코드·연동 허브 URL 기준.
    (과거 workflow_rfp 연결이 있어도 연동 허브에서 진행한 단계를 반영한다.)
    """
    iid = int(ir.id)
    owner_id = int(ir.user_id)
    fs_s = (getattr(ir, "fs_status", None) or "none").strip()
    dc_s = (getattr(ir, "delivered_code_status", None) or "none").strip()
    pipeline = fs_s != "none" or dc_s != "none"
    is_operator = bool(
        user and (getattr(user, "is_admin", False) or getattr(user, "is_consultant", False))
    )
    has_fs = pipeline or is_operator
    fs_href = integration_hub_url(iid, "fs") if has_fs else None

    st = (getattr(ir, "status", None) or "").strip().lower()
    iv = (getattr(ir, "interview_status", None) or "").strip()
    prop = (getattr(ir, "proposal_text", None) or "").strip()
    nmsg = len(getattr(ir, "interview_messages", None) or [])

    has_proposal = bool(prop) or iv == "generating_proposal"
    if iv == "generating_proposal":
        proposal_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="proposal")
    elif prop:
        proposal_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="proposal")
    else:
        proposal_href = None

    has_interview = False
    interview_href: str | None = None
    if st != "draft":
        if iv == "generating_proposal":
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="interview", view_summary=True
            )
        elif iv == "in_progress":
            has_interview = True
            interview_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="interview")
        elif iv == "completed":
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="interview", view_summary=True
            )
        elif nmsg > 0:
            has_interview = True
            interview_href = menu_entity_hub_url(
                user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="interview", view_summary=True
            )
        elif st == "submitted" and iv == "pending":
            has_interview = True
            interview_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="interview")

    request_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="request")

    dc_started = dc_s != "none"
    has_ref_dev = reference_code_payload_has_content(getattr(ir, "reference_code_payload", None))

    if dc_started:
        dev_code_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="devcode")
    elif has_ref_dev:
        dev_code_href = menu_entity_hub_url(user=user, owner_user_id=owner_id, request_kind="integration", request_id=iid, phase="devcode")
    else:
        dev_code_href = None

    has_dev_code = dc_started or has_ref_dev

    return {
        "has_dev_code": has_dev_code,
        "dev_code_href": dev_code_href,
        "has_fs": has_fs,
        "fs_href": fs_href,
        "has_proposal": has_proposal,
        "proposal_href": proposal_href,
        "has_interview": has_interview,
        "interview_href": interview_href,
        "request_href": request_href,
    }


def abap_analysis_phase_gates(row: models.AbapAnalysisRequest, user: Optional[Any] = None) -> dict[str, Any]:
    """
    분석·개선(abap_analysis_requests) 목록 카드용 단계 링크.
    신규/연동과 동일: 요청 → 분석결과(인터뷰 대체) → 제안서 → FS → 개발코드.
    """
    aid = int(row.id)
    owner_id = int(row.user_id)
    draft = bool(getattr(row, "is_draft", False))
    base = menu_abap_detail_url(user=user, owner_user_id=owner_id, request_id=aid, draft=draft)
    request_href = f"{base}#abap-phase-request" if not draft else None

    analyzed = bool(getattr(row, "is_analyzed", False)) and not draft
    has_analysis = analyzed
    analysis_href = f"{base}#abap-phase-analysis" if has_analysis else None

    fs_s = ((getattr(row, "fs_status", None) or "none").strip().lower() or "none")
    dc_s = ((getattr(row, "delivered_code_status", None) or "none").strip().lower() or "none")
    pipeline = fs_s not in ("none", "") or dc_s not in ("none", "")
    has_fs = pipeline
    fs_href = f"{base}#abap-phase-fs" if has_fs else None

    dc_started = dc_s not in ("none", "")
    has_dev_code = dc_started
    dev_code_href = f"{base}#abap-phase-devcode" if has_dev_code else None

    iv = (getattr(row, "interview_status", None) or "").strip()
    prop = (getattr(row, "proposal_text", None) or "").strip()
    has_proposal = analyzed
    proposal_href = f"{base}#abap-phase-proposal" if has_proposal else None

    return {
        "has_dev_code": has_dev_code,
        "dev_code_href": dev_code_href,
        "has_fs": has_fs,
        "fs_href": fs_href,
        "has_proposal": has_proposal,
        "proposal_href": proposal_href,
        "has_analysis": has_analysis,
        "analysis_href": analysis_href,
        "has_interview": False,
        "interview_href": None,
        "request_href": request_href,
    }


def rfp_for_owner_or_admin(
    db: Session,
    *,
    user,
    rfp_id: int,
    load_messages: bool = False,
    load_fs_supplements: bool = False,
    load_followup_messages: bool = False,
) -> models.RFP | None:
    """조회 페이지용: 본인, 관리자, 또는 해당 건에 오퍼/매칭이 있는 컨설턴트."""
    q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
    preload = []
    if load_messages:
        preload.append(joinedload(models.RFP.messages))
    if load_fs_supplements:
        preload.append(joinedload(models.RFP.fs_supplements))
    if load_followup_messages:
        preload.append(joinedload(models.RFP.followup_messages))
    if preload:
        q = q.options(*preload)
    if getattr(user, "is_admin", False):
        return q.first()
    if getattr(user, "is_consultant", False):
        owned = q.filter(models.RFP.user_id == user.id).first()
        if owned:
            return owned
        if consultant_has_request_offer(
            db, consultant_user_id=user.id, request_kind="rfp", request_id=rfp_id
        ):
            return q.first()
        return None
    return q.filter(models.RFP.user_id == user.id).first()


def rfp_for_hub_readonly_embed(
    db: Session,
    *,
    user,
    rfp_id: int,
    load_messages: bool = False,
    load_fs_supplements: bool = False,
    load_followup_messages: bool = False,
) -> models.RFP | None:
    """요청 Console iframe(읽기 전용): 관리자·컨설턴트는 콘솔 목록과 동일하게 전체 RFP 미리보기."""
    if getattr(user, "is_admin", False) or getattr(user, "is_consultant", False):
        q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
        preload = [joinedload(models.RFP.owner)]
        if load_messages:
            preload.append(joinedload(models.RFP.messages))
        if load_fs_supplements:
            preload.append(joinedload(models.RFP.fs_supplements))
        if load_followup_messages:
            preload.append(joinedload(models.RFP.followup_messages))
        return q.options(*preload).first()
    return rfp_for_owner_or_admin(
        db,
        user=user,
        rfp_id=rfp_id,
        load_messages=load_messages,
        load_fs_supplements=load_fs_supplements,
        load_followup_messages=load_followup_messages,
    )


def rfp_owned_only(db: Session, *, user_id: int, rfp_id: int) -> models.RFP | None:
    """변경(POST) 처리용: 소유자만."""
    return db.query(models.RFP).filter(
        models.RFP.id == rfp_id,
        models.RFP.user_id == user_id,
    ).first()
