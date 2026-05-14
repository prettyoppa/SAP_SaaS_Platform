"""요청 소유자 → 오퍼 컨설턴트 문의(이메일·SMS, 이력 저장)."""

from __future__ import annotations

import logging
import os
import re
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session, joinedload

from . import models
from .email_smtp import send_plain_notification_email
from .sms_sender import send_offer_inquiry_sms

# 플랫폼 내 1차 문의·답변 상한(다수 마켓플레이스 첫 메시지 수백~1,500자 수준). 상세 협의는 매칭 후 연락처로 이어가도록 유도.
MAX_INQUIRY_BODY_LEN = 1000
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


def site_public_origin(request: Any) -> str:
    """사이트 루트 URL (스킴+호스트)."""
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    return str(getattr(request, "base_url", "") or "").rstrip("/")


def sanitize_console_readonly_return_url(raw: str | None) -> str | None:
    """오퍼 문의 답변 후 요청 Console iframe으로 복귀할 안전한 상대 경로."""
    s = (raw or "").strip()
    if not s.startswith("/") or ".." in s or "\n" in s or "\r" in s:
        return None
    if "console-readonly" not in s:
        return None
    for prefix in ("/rfp/", "/integration/", "/abap-analysis/"):
        if s.startswith(prefix):
            return s
    return None


def owner_hub_proposal_public_url(request: Any, request_kind: str, request_id: int) -> str:
    k = (request_kind or "").strip().lower()
    rid = int(request_id)
    if k == "rfp":
        return public_request_url(request, f"/rfp/{rid}?phase=proposal")
    if k == "analysis":
        return public_request_url(request, f"/abap-analysis/{rid}#abap-phase-offers")
    if k == "integration":
        return public_request_url(request, f"/integration/{rid}?phase=proposal")
    return public_request_url(request, "/request-console")


def format_reply_via_console_ko(request: Any) -> str:
    return f"문의 내용에 대한 답변은 {site_public_origin(request)} 의 요청 Console 메뉴에서 가능합니다."


def format_owner_reply_followup_ko(request: Any) -> str:
    return f"답변 내용은 {site_public_origin(request)} 에서도 확인 가능하며 추가 문의도 가능합니다."


def consultant_profile_email_lines(consultant: models.User) -> str:
    """첨부 없이 본문에 넣는 프로필 요약(텍스트만)."""
    name = (getattr(consultant, "full_name", None) or "").strip()
    company = (getattr(consultant, "company", None) or "").strip()
    lines = [
        "[프로필 안내] 첨부 파일은 보내지 않습니다. 아래는 텍스트 요약이며, 상세는 사이트에서 확인해 주세요.",
    ]
    if name:
        lines.append(f"표시 이름: {name}")
    if company:
        lines.append(f"소속: {company}")
    lines.append("전체 프로필·첨부 자료는 요청 상세(제안서 단계) 오퍼 목록에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _member_ops_sms_target(user: models.User) -> tuple[bool, str | None]:
    sms_ok = bool(
        getattr(user, "ops_sms_opt_in", False)
        and getattr(user, "phone_verified", False)
        and phone_e164_for_sms(getattr(user, "phone_number", None))
    )
    phone = phone_e164_for_sms(getattr(user, "phone_number", None)) if sms_ok else None
    return sms_ok, phone


def notify_request_owner_new_console_offer(
    *,
    request: Any,
    owner: models.User,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> None:
    """요청 Console에서 새 오퍼 등록 시 요청자에게 이메일·SMS(수신 동의 시)."""
    email_ok = bool(getattr(owner, "ops_email_opt_in", False))
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    to_email = (owner.email or "").strip()
    if email_ok and not to_email:
        email_ok = False
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "new offer notify skipped (no owner channel) owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )
        return
    hub = owner_hub_proposal_public_url(request, request_kind, request_id)
    label = inquiry_request_label(
        SimpleNamespace(request_kind=request_kind, request_id=request_id, id=0)
    )
    subject = f"[SAP Dev Hub] 새 오퍼 알림 — {request_title[:60]}"
    body_email = (
        "안녕하세요.\n\n"
        "컨설턴트가 귀하의 요청에 오퍼했습니다.\n\n"
        f"요청 ID: {label}\n"
        f"요청 제목: {request_title}\n\n"
        f"{consultant_profile_email_lines(consultant)}\n\n"
        f"요청·오퍼 확인:\n{hub}\n"
    )
    try:
        if email_ok and to_email:
            send_plain_notification_email(to_email, subject, body_email)
        if sms_ok and phone_e164:
            sms_body = (
                f"[SAP Dev Hub 오퍼]\n"
                f"{request_title[:50]}\n"
                f"컨설턴트가 오퍼했습니다.\n"
                f"{hub}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="new_offer")
    except Exception:
        logger.exception(
            "notify_request_owner_new_console_offer failed owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )


def notify_consultant_request_matched(
    *,
    request: Any,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> None:
    """요청자가 매칭했을 때 매칭된 컨설턴트에게 이메일·SMS(수신 동의 시)."""
    email_ok = bool(getattr(consultant, "ops_email_opt_in", False))
    sms_ok, phone_e164 = _member_ops_sms_target(consultant)
    to_email = (consultant.email or "").strip()
    if email_ok and not to_email:
        email_ok = False
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "match notify skipped (no consultant channel) consultant_id=%s kind=%s rid=%s",
            getattr(consultant, "id", None),
            request_kind,
            request_id,
        )
        return
    label = inquiry_request_label(
        SimpleNamespace(request_kind=request_kind, request_id=request_id, id=0)
    )
    console_url = public_request_url(request, "/request-console?kind=matching")
    hub = owner_hub_proposal_public_url(request, request_kind, request_id)
    subject = f"[SAP Dev Hub] 요청 매칭 — {request_title[:60]}"
    body_email = (
        "안녕하세요.\n\n"
        "요청자가 귀하의 오퍼로 매칭했습니다.\n\n"
        f"요청 ID: {label}\n"
        f"요청 제목: {request_title}\n\n"
        f"요청 Console(매칭)에서 확인:\n{console_url}\n\n"
        f"요청 상세:\n{hub}\n"
    )
    try:
        if email_ok and to_email:
            send_plain_notification_email(to_email, subject, body_email)
        if sms_ok and phone_e164:
            sms_body = (
                f"[SAP Dev Hub 매칭]\n"
                f"{request_title[:45]}\n"
                f"요청자가 매칭했습니다.\n"
                f"{console_url}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_match")
    except Exception:
        logger.exception(
            "notify_consultant_request_matched failed consultant_id=%s kind=%s rid=%s",
            getattr(consultant, "id", None),
            request_kind,
            request_id,
        )


def consultant_has_pending_match_notice(db: Session, consultant_user_id: int) -> bool:
    q = (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == int(consultant_user_id),
            models.RequestOffer.status == "matched",
            models.RequestOffer.match_notice_pending.is_(True),
        )
        .first()
    )
    return q is not None


def clear_match_notice_pending_for_consultant(db: Session, consultant_user_id: int) -> None:
    (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.consultant_user_id == int(consultant_user_id),
            models.RequestOffer.match_notice_pending.is_(True),
        )
        .update({"match_notice_pending": False}, synchronize_session=False)
    )


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


def pending_inquiry_reply_offer_ids_all(db: Session) -> set[int]:
    """전체 오퍼 중 회원 문의에 컨설턴트 답이 필요한 offer id (관리자 요청 Console 등)."""
    offers = (
        db.query(models.RequestOffer.id)
        .filter(models.RequestOffer.status.in_(("offered", "matched")))
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
    request: Any,
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
    console_line = format_reply_via_console_ko(request)
    body_email = (
        f"요청 ID: {inquiry_request_label(offer)}\n"
        f"요청: {request_title}\n\n"
        f"{console_line}\n\n"
        f"문의 내용:\n{body}\n"
    )

    phone_e164 = phone_e164_for_sms(getattr(consultant, "phone_number", None)) if sms_ok else None
    sms_body = (
        f"[SAP Dev Hub 문의]\n"
        f"{request_title[:40]}\n"
        f"{body[:300]}{'…' if len(body) > 300 else ''}\n"
        f"{site_public_origin(request)}"
    )

    email_sent = False
    sms_sent = False
    try:
        if email_ok:
            send_plain_notification_email(to_email, subject, body_email)
            email_sent = True
        if sms_ok and phone_e164:
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_inquiry")
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


def send_consultant_matched_first_inquiry_to_owner(
    db: Session,
    *,
    request: Any,
    consultant: models.User,
    offer: models.RequestOffer,
    owner: models.User,
    request_title: str,
    request_detail_url: str,
    body_raw: str,
) -> tuple[str | None, models.RequestOfferInquiry | None]:
    """매칭된 오퍼에서만, 문의 이력이 없을 때 컨설턴트가 회원에게 첫 문의(저장 + 회원 이메일)."""
    if int(offer.consultant_user_id) != int(consultant.id):
        return "이 오퍼에 대한 문의 권한이 없습니다.", None
    if (offer.status or "").strip() != "matched":
        return "매칭된 요청에만 먼저 문의할 수 있습니다.", None
    existing = (
        db.query(models.RequestOfferInquiry)
        .filter(models.RequestOfferInquiry.request_offer_id == offer.id)
        .count()
    )
    if existing > 0:
        return "이미 문의 이력이 있습니다. 문의 내역에서 회원 문의에 답변해 주세요.", None

    body = (body_raw or "").strip()
    if len(body) < 1:
        return "문의 내용을 입력해 주세요.", None
    if len(body) > MAX_INQUIRY_BODY_LEN:
        return f"문의 내용은 {MAX_INQUIRY_BODY_LEN}자 이하로 입력해 주세요.", None

    owner_email = (owner.email or "").strip()
    email_channel = bool(getattr(owner, "ops_email_opt_in", False)) and bool(owner_email)
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    if not email_channel and not (sms_ok and phone_e164):
        return (
            "요청자는 업무 이메일·SMS 수신에 동의하지 않았거나 휴대폰이 인증되지 않아 전송할 수 없습니다.",
            None,
        )

    subject = f"[SAP Dev Hub] 컨설턴트 문의 — {request_title[:80]}"
    follow_line = format_owner_reply_followup_ko(request)
    body_email = (
        f"요청 ID: {inquiry_request_label(offer)}\n"
        f"요청: {request_title}\n\n"
        f"{follow_line}\n\n"
        f"문의 내용:\n{body}\n"
    )

    row = models.RequestOfferInquiry(
        request_offer_id=offer.id,
        author_user_id=consultant.id,
        body=body,
        email_sent=False,
        sms_sent=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        if email_channel:
            send_plain_notification_email(owner_email, subject, body_email)
            row.email_sent = True
        if sms_ok and phone_e164:
            sms_body = (
                f"[SAP Dev Hub]\n"
                f"매칭된 요청에 컨설턴트 문의가 도착했습니다.\n"
                f"{request_title[:40]}\n"
                f"{site_public_origin(request)}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="consultant_first_inquiry")
            row.sms_sent = True
        db.add(row)
        db.commit()
    except Exception:
        logger.exception("consultant first inquiry notify failed offer_id=%s", offer.id)
    return None, row


def send_consultant_offer_inquiry_reply(
    db: Session,
    *,
    request: Any,
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
    email_channel = bool(getattr(owner, "ops_email_opt_in", False)) and bool(owner_email)
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    subject = f"[SAP Dev Hub] 문의 답변 — {request_title[:80]}"
    follow_line = format_owner_reply_followup_ko(request)
    body_email = (
        f"요청 ID: {inquiry_request_label(offer)}\n"
        f"요청: {request_title}\n\n"
        f"{follow_line}\n\n"
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
    try:
        if email_channel:
            send_plain_notification_email(owner_email, subject, body_email)
            row.email_sent = True
        if sms_ok and phone_e164:
            sms_body = (
                f"[SAP Dev Hub 문의 답변]\n"
                f"{request_title[:40]}\n"
                f"{body[:200]}{'…' if len(body) > 200 else ''}\n"
                f"{site_public_origin(request)}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_inquiry_reply")
            row.sms_sent = True
        db.add(row)
        db.commit()
    except Exception:
        logger.exception("consultant inquiry reply notify failed offer_id=%s", offer.id)
    return None, row
