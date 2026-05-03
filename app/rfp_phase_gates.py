"""RFP 리스트 타일의 단계 버튼(개발코드·FS·제안서·인터뷰·요청) 가용성·링크."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from . import models
from .paid_tier import PAID_ACTIVE
from .rfp_hub import rfp_hub_url
from .rfp_reference_code import normalize_reference_code_payload


def _reference_code_has_content(rfp: models.RFP) -> bool:
    raw = normalize_reference_code_payload(getattr(rfp, "reference_code_payload", None))
    if not raw:
        return False
    try:
        data: dict[str, Any] = json.loads(raw)
    except Exception:
        return False
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


def rfp_phase_gates(rfp: models.RFP, user: Optional[Any] = None) -> dict[str, Any]:
    """
    Jinja 필터용. has_* / href 키는 템플릿에서 사용.
    FS: 결제 완료·FS/납품 파이프라인 시작 후 활성 — **관리자**는 결제 전에도 링크 허브로 진입 가능(납품 콘솔 테스트).
    개발코드 버튼: (1) 고객이 첨부한 참조 ABAP → /rfp/{id}/dev-code
                     (2) 에이전트 납품 ABAP 진행·완료 → /rfp/{id}/fs (같은 허브에서 미리보기·다운로드)
    """
    rid = rfp.id
    has_ref_dev = _reference_code_has_content(rfp)

    paid_on = (rfp.paid_engagement_status or "none").strip() == PAID_ACTIVE
    fs_s = (getattr(rfp, "fs_status", None) or "none").strip()
    dc_s = (getattr(rfp, "delivered_code_status", None) or "none").strip()
    pipeline = fs_s != "none" or dc_s != "none"
    is_admin = bool(user and getattr(user, "is_admin", False))
    has_fs = paid_on or pipeline or is_admin
    fs_href = rfp_hub_url(rid, "fs") if has_fs else None

    st = (rfp.status or "").strip()
    iv = (rfp.interview_status or "").strip()
    prop = (rfp.proposal_text or "").strip()
    nmsg = len(getattr(rfp, "messages", None) or [])

    has_proposal = bool(prop) or iv == "generating_proposal"
    if iv == "generating_proposal":
        proposal_href = rfp_hub_url(rid, "proposal")
    elif prop:
        proposal_href = rfp_hub_url(rid, "proposal")
    else:
        proposal_href = None

    has_interview = False
    interview_href: str | None = None
    if st != "draft":
        if iv == "generating_proposal":
            has_interview = True
            interview_href = rfp_hub_url(rid, "interview", view_summary=True)
        elif iv == "in_progress":
            has_interview = True
            interview_href = rfp_hub_url(rid, "interview")
        elif iv == "completed":
            has_interview = True
            interview_href = rfp_hub_url(rid, "interview", view_summary=True)
        elif nmsg > 0:
            has_interview = True
            interview_href = rfp_hub_url(rid, "interview", view_summary=True)
        elif st == "submitted" and iv == "pending":
            has_interview = True
            interview_href = rfp_hub_url(rid, "interview")

    request_href = rfp_hub_url(rid, "request")

    dc_started = dc_s != "none"
    if dc_started:
        dev_code_href = rfp_hub_url(rid, "devcode")
    elif has_ref_dev:
        dev_code_href = rfp_hub_url(rid, "devcode")
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


def rfp_for_owner_or_admin(
    db: Session,
    *,
    user,
    rfp_id: int,
    load_messages: bool = False,
    load_fs_supplements: bool = False,
    load_followup_messages: bool = False,
) -> models.RFP | None:
    """조회 페이지용: 본인 또는 관리자."""
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
    if not user.is_admin:
        q = q.filter(models.RFP.user_id == user.id)
    return q.first()


def rfp_owned_only(db: Session, *, user_id: int, rfp_id: int) -> models.RFP | None:
    """변경(POST) 처리용: 소유자만."""
    return db.query(models.RFP).filter(
        models.RFP.id == rfp_id,
        models.RFP.user_id == user_id,
    ).first()
