"""RFP 리스트 타일의 단계 버튼(개발코드·FS·제안서·인터뷰·요청) 가용성·링크."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session, joinedload

from . import models
from .paid_tier import PAID_ACTIVE
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


def rfp_phase_gates(rfp: models.RFP) -> dict[str, Any]:
    """
    Jinja 필터용. has_* / href 키는 템플릿에서 사용.
    FS: 유료(결제 활성화) 건에서만 활성 버튼.
    """
    rid = rfp.id
    has_dev = _reference_code_has_content(rfp)

    paid_on = (rfp.paid_engagement_status or "none").strip() == PAID_ACTIVE
    has_fs = paid_on
    fs_href = f"/rfp/{rid}/fs" if paid_on else None

    st = (rfp.status or "").strip()
    iv = (rfp.interview_status or "").strip()
    prop = (rfp.proposal_text or "").strip()
    nmsg = len(getattr(rfp, "messages", None) or [])

    has_proposal = bool(prop) or iv == "generating_proposal"
    if iv == "generating_proposal":
        proposal_href = f"/rfp/{rid}/proposal/generating"
    elif prop:
        proposal_href = f"/rfp/{rid}/proposal"
    else:
        proposal_href = None

    has_interview = False
    interview_href: str | None = None
    if st != "draft":
        if iv == "generating_proposal":
            has_interview = True
            interview_href = f"/rfp/{rid}/interview/summary"
        elif iv == "in_progress":
            has_interview = True
            interview_href = f"/rfp/{rid}/interview"
        elif iv == "completed":
            has_interview = True
            interview_href = f"/rfp/{rid}/interview/summary"
        elif nmsg > 0:
            has_interview = True
            interview_href = f"/rfp/{rid}/interview/summary"
        elif st == "submitted" and iv == "pending":
            has_interview = True
            interview_href = f"/rfp/{rid}/interview"

    request_href = f"/rfp/{rid}/request"

    return {
        "has_dev_code": has_dev,
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
) -> models.RFP | None:
    """조회 페이지용: 본인 또는 관리자."""
    q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
    if load_messages:
        q = q.options(joinedload(models.RFP.messages))
    if not user.is_admin:
        q = q.filter(models.RFP.user_id == user.id)
    return q.first()


def rfp_owned_only(db: Session, *, user_id: int, rfp_id: int) -> models.RFP | None:
    """변경(POST) 처리용: 소유자만."""
    return db.query(models.RFP).filter(
        models.RFP.id == rfp_id,
        models.RFP.user_id == user_id,
    ).first()
