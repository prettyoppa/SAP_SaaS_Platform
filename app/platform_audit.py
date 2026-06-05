"""회원 주요 운영 이벤트 기록(관리자·테스트 계정 제외)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger(__name__)

EVENT_MEMBER_REGISTERED = "member_registered"
EVENT_REQUEST_SUBMITTED_ABAP = "request_submitted_abap"
EVENT_REQUEST_SUBMITTED_RFP = "request_submitted_rfp"
EVENT_REQUEST_SUBMITTED_INTEGRATION = "request_submitted_integration"
EVENT_OFFER_CREATED = "offer_created"
EVENT_OFFER_MATCHED = "offer_matched"
EVENT_WALLET_TOPUP_SUBMITTED = "wallet_topup_submitted"
EVENT_SETTLEMENT_BANK_SUBMITTED = "settlement_bank_submitted"
EVENT_SETTLEMENT_FUNDED = "settlement_funded"

EVENT_LABEL_KO: dict[str, str] = {
    EVENT_MEMBER_REGISTERED: "회원가입",
    EVENT_REQUEST_SUBMITTED_ABAP: "ABAP 분석 요청 제출",
    EVENT_REQUEST_SUBMITTED_RFP: "신규 개발 요청 제출",
    EVENT_REQUEST_SUBMITTED_INTEGRATION: "연동 개발 요청 제출",
    EVENT_OFFER_CREATED: "오퍼 제출",
    EVENT_OFFER_MATCHED: "오퍼 매칭",
    EVENT_WALLET_TOPUP_SUBMITTED: "AI 크레딧 충전 신청",
    EVENT_SETTLEMENT_BANK_SUBMITTED: "납품 대금 계좌이체 신청",
    EVENT_SETTLEMENT_FUNDED: "납품 대금 입금 완료",
}

EVENT_LABEL_EN: dict[str, str] = {
    EVENT_MEMBER_REGISTERED: "Registration",
    EVENT_REQUEST_SUBMITTED_ABAP: "ABAP analysis request submitted",
    EVENT_REQUEST_SUBMITTED_RFP: "New development request submitted",
    EVENT_REQUEST_SUBMITTED_INTEGRATION: "Integration request submitted",
    EVENT_OFFER_CREATED: "Offer submitted",
    EVENT_OFFER_MATCHED: "Offer matched",
    EVENT_WALLET_TOPUP_SUBMITTED: "AI credit top-up submitted",
    EVENT_SETTLEMENT_BANK_SUBMITTED: "Project settlement bank transfer submitted",
    EVENT_SETTLEMENT_FUNDED: "Project settlement paid",
}


def event_label(event_type: str, *, lang: str = "ko") -> str:
    key = (event_type or "").strip()
    if lang == "en":
        return EVENT_LABEL_EN.get(key, key)
    return EVENT_LABEL_KO.get(key, key)


def should_record_actor(user: models.User | None) -> bool:
    if user is None:
        return False
    if getattr(user, "is_admin", False):
        return False
    if getattr(user, "is_test_account", False):
        return False
    return bool((user.email or "").strip())


def record_event(
    db: Session,
    actor: models.User | None,
    event_type: str,
    *,
    target_kind: str | None = None,
    target_id: int | None = None,
    detail: str | None = None,
) -> None:
    """이벤트 1건 기록. 관리자·테스트 계정은 무시."""
    if not should_record_actor(actor):
        return
    et = (event_type or "").strip()
    if not et:
        return
    email = (actor.email or "").strip()[:320]
    if not email:
        return
    det = (detail or "").strip()[:500] or None
    tk = (target_kind or "").strip()[:32] or None
    try:
        row = models.PlatformAuditEvent(
            actor_user_id=int(actor.id),
            actor_email=email,
            event_type=et,
            target_kind=tk,
            target_id=int(target_id) if target_id is not None else None,
            detail=det,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("platform audit record failed event_type=%s actor=%s", et, email)


def record_event_for_user_id(
    db: Session,
    user_id: int,
    event_type: str,
    **kwargs: Any,
) -> None:
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    record_event(db, user, event_type, **kwargs)
