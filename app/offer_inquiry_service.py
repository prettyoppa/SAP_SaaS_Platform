"""요청 소유자 → 오퍼 컨설턴트 문의(이메일·SMS, 이력 저장)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from sqlalchemy.orm import Session, joinedload

from . import models
from .email_smtp import send_plain_notification_email
from .sms_sender import send_offer_inquiry_sms

MAX_INQUIRY_BODY_LEN = 2000
logger = logging.getLogger(__name__)


def inquiry_request_label(offer: models.RequestOffer) -> str:
    """요청 콘솔과 동일한 표기 (RFP-3, ANA-3, INT-3)."""
    k = (getattr(offer, "request_kind", None) or "").strip().lower()
    try:
        rid = int(getattr(offer, "request_id", 0) or 0)
    except (TypeError, ValueError):
        rid = 0
    if k == "rfp":
        return f"RFP-{rid}"
    if k == "analysis":
        return f"ANA-{rid}"
    if k == "integration":
        return f"INT-{rid}"
    return f"REQ-{rid}"


def public_request_url(request: Any, path: str) -> str:
    """절대 URL (PUBLIC_BASE_URL 우선). path는 / 로 시작."""
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    p = path if path.startswith("/") else "/" + path
    if env:
        return env + p
    return str(request.base_url).rstrip("/") + p


def phone_e164_for_sms(raw: str | None) -> str | None:
    """DB에 저장된 번호를 E.164(+...)로 맞춘다. 이미 +로 시작하면 검증만."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("+"):
        s2 = re.sub(r"[\s\-\(\)]", "", s)
        digits = s2[1:]
        if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
            return None
        return f"+{digits}"
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if digits.startswith("82"):
        rest = digits[2:]
        if rest.startswith("0"):
            rest = rest[1:]
        return "+82" + rest
    if digits.startswith("0") and len(digits) >= 10:
        return "+82" + digits[1:]
    return None


def offer_inquiry_needs_consultant_reply(db: Session, offer_id: int) -> bool:
    """해당 오퍼에 회원(요청자) 쪽이 마지막으로 남긴 문의에 컨설턴트 답이 없으면 True."""
    rows = (
        db.query(models.RequestOfferInquiry)
        .filter(models.RequestOfferInquiry.request_offer_id == int(offer_id))
        .order_by(models.RequestOfferInquiry.created_at.asc())
        .all()
    )
    if not rows:
        return False
    of = db.query(models.RequestOffer).filter(models.RequestOffer.id == int(offer_id)).first()
    if not of:
        return False
    return int(rows[-1].author_user_id) != int(of.consultant_user_id)


def pending_inquiry_reply_offer_ids_for_consultant(db: Session, consultant_user_id: int) -> set[int]:
    """답변 대기 중인 오퍼 id 집합."""
    offers = (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == int(consultant_user_id),
            models.RequestOffer.status.in_(("offered", "matched")),
        )
        .all()
    )
    out: set[int] = set()
    for (oid,) in offers:
        if offer_inquiry_needs_consultant_reply(db, int(oid)):
            out.add(int(oid))
    return out


def consultant_has_any_pending_inquiry_reply(db: Session, consultant_user_id: int) -> bool:
    return bool(pending_inquiry_reply_offer_ids_for_consultant(db, consultant_user_id))


def inquiries_by_offer_id(db: Session, offer_ids: list[int]) -> dict[int, list[models.RequestOfferInquiry]]:
    if not offer_ids:
        return {}
    rows = (
        db.query(models.RequestOfferInquiry)
        .options(joinedload(models.RequestOfferInquiry.author))
        .filter(models.RequestOfferInquiry.request_offer_id.in_(offer_ids))
        .order_by(models.RequestOfferInquiry.created_at.asc())
        .all()
    )
    out: dict[int, list[models.RequestOfferInquiry]] = {}
    for r in rows:
        out.setdefault(int(r.request_offer_id), []).append(r)
    return out


def send_offer_inquiry_from_owner(
    db: Session,
    *,
    author: models.User,
    offer: models.RequestOffer,
    consultant: models.User,
    request_title: str,
    request_detail_url: str,
    body_raw: str,
) -> tuple[str | None, models.RequestOfferInquiry | None]:
    """
    검증·발송·DB 저장. 성공 시 (None, row), 실패 시 (에러 메시지, None).
    """
    body = (body_raw or "").strip()
    if len(body) < 1:
        return "문의 내용을 입력해 주세요.", None
    if len(body) > MAX_INQUIRY_BODY_LEN:
        return f"문의 내용은 {MAX_INQUIRY_BODY_LEN}자 이하로 입력해 주세요.", None

    email_ok = bool(getattr(consultant, "ops_email_opt_in", False))
    sms_ok = bool(
        getattr(consultant, "ops_sms_opt_in", False)
        and getattr(consultant, "phone_verified", False)
        and phone_e164_for_sms(getattr(consultant, "phone_number", None))
    )
    if not email_ok and not sms_ok:
        return (
            "이 컨설턴트는 업무 이메일·SMS 수신에 동의하지 않았거나 휴대폰이 인증되지 않아 전송할 수 없습니다.",
            None,
        )

    to_email = (consultant.email or "").strip()
    if email_ok and not to_email:
        return "컨설턴트 이메일이 없어 이메일로 보낼 수 없습니다.", None

    subject = f"[SAP Dev Hub] 요청 문의 — {request_title[:80]}"
    # 이메일은 Catch Lab 발신이나, 본문에 요청자 로그인 이메일은 포함하지 않음(개인정보 최소화).
    owner_line = f"요청자: {author.full_name}"
    body_email = (
        f"{owner_line}\n"
        f"요청 ID: {inquiry_request_label(offer)}\n"
        f"요청: {request_title}\n"
        f"링크: {request_detail_url}\n\n"
        f"문의 내용:\n{body}\n"
    )

    phone_e164 = phone_e164_for_sms(getattr(consultant, "phone_number", None)) if sms_ok else None
    sms_body = (
        f"[SAP Dev Hub 문의] {request_title[:40]}\n"
        f"{author.full_name}: {body[:300]}{'…' if len(body) > 300 else ''}\n"
        f"{request_detail_url}"
    )

    email_sent = False
    sms_sent = False
    try:
        if email_ok:
            send_plain_notification_email(to_email, subject, body_email)
            email_sent = True
        if sms_ok and phone_e164:
            send_offer_inquiry_sms(phone_e164, sms_body)
            sms_sent = True
    except Exception as ex:
        return (str(ex) or "전송에 실패했습니다."), None

    row = models.RequestOfferInquiry(
        request_offer_id=offer.id,
        author_user_id=author.id,
        body=body,
        email_sent=email_sent,
        sms_sent=sms_sent,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return None, row


def send_consultant_offer_inquiry_reply(
    db: Session,
    *,
    consultant: models.User,
    offer: models.RequestOffer,
    owner: models.User,
    request_title: str,
    request_detail_url: str,
    body_raw: str,
) -> tuple[str | None, models.RequestOfferInquiry | None]:
    """컨설턴트가 요청자 문의에 답변(저장 + 요청자에게 이메일 알림)."""
    if int(offer.consultant_user_id) != int(consultant.id):
        return "이 오퍼에 대한 답변 권한이 없습니다.", None
    body = (body_raw or "").strip()
    if len(body) < 1:
        return "답변 내용을 입력해 주세요.", None
    if len(body) > MAX_INQUIRY_BODY_LEN:
        return f"답변은 {MAX_INQUIRY_BODY_LEN}자 이하로 입력해 주세요.", None

    rows = (
        db.query(models.RequestOfferInquiry)
        .filter(models.RequestOfferInquiry.request_offer_id == offer.id)
        .order_by(models.RequestOfferInquiry.created_at.asc())
        .all()
    )
    if not rows:
        return "문의 이력이 없습니다.", None
    last = rows[-1]
    if int(last.author_user_id) == int(consultant.id):
        return "요청자 문의에 대한 답변이 이미 반영된 상태입니다.", None

    owner_email = (owner.email or "").strip()
    subject = f"[SAP Dev Hub] 문의 답변 — {request_title[:80]}"
    body_email = (
        f"컨설턴트: {consultant.full_name}\n"
        f"요청 ID: {inquiry_request_label(offer)}\n"
        f"요청: {request_title}\n"
        f"링크: {request_detail_url}\n\n"
        f"답변:\n{body}\n"
    )

    row = models.RequestOfferInquiry(
        request_offer_id=offer.id,
        author_user_id=consultant.id,
        parent_inquiry_id=last.id,
        body=body,
        email_sent=False,
        sms_sent=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if owner_email:
        try:
            send_plain_notification_email(owner_email, subject, body_email)
            row.email_sent = True
            db.add(row)
            db.commit()
        except Exception:
            logger.exception("consultant inquiry reply email failed offer_id=%s", offer.id)
    return None, row
