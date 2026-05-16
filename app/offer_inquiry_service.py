"""요청 소유자 → 오퍼 컨설턴트 문의(이메일·SMS, 이력 저장)."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session, joinedload

from . import models
from .email_smtp import send_plain_notification_email
from .sms_sender import send_offer_inquiry_sms

# 플랫폼 내 1차 문의·답변 상한(다수 마켓플레이스 첫 메시지 수백~1,500자 수준). 상세 협의는 매칭 후 연락처로 이어가도록 유도.
MAX_INQUIRY_BODY_LEN = 1000
# 요청 Console 오퍼 확인창 (신규·분석·연동 공통 — 오퍼 버튼은 Console에만 있음)
CONSOLE_OFFER_CONFIRM_MESSAGE_KO = (
    "요청자에게 이메일 및 SMS로 알림이 전송되며, "
    "요청자는 오퍼한 컨설턴트님의 프로필 확인이 가능해집니다."
)
OFFER_MATCH_ERR_BLOCKED = "match_blocked"

from .request_offer_lifecycle import (
    MATCH_ERR_CANCEL_DELIVERABLES,
    MATCH_ERR_FORBIDDEN,
    OFFER_ERR_FORBIDDEN,
    OFFER_ERR_NOT_WITHDRAWABLE,
    OFFER_STATUS_MATCHED,
    OFFER_STATUS_OFFERED,
    OFFER_STATUS_WITHDRAWN,
    request_has_deliverables,
    request_owner_user_id,
)

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
        return public_request_url(request, f"/abap-analysis/{rid}#abap-phase-proposal")
    if k == "integration":
        return public_request_url(request, f"/integration/{rid}?phase=proposal")
    return public_request_url(request, "/request-console")


def format_reply_via_console_ko(request: Any) -> str:
    return f"문의 내용에 대한 답변은 {site_public_origin(request)} 의 요청 Console 메뉴에서 가능합니다."


def format_owner_reply_followup_ko(request: Any) -> str:
    return (
        f"로그인 후 해당 요청 상세(제안서 단계)에서도 확인·추가 문의가 가능합니다. "
        f"({site_public_origin(request)})"
    )


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


def _owner_ops_email_channel(owner: models.User) -> tuple[bool, str]:
    """문의/답변 발송과 동일: 업무 이메일 수신 동의 + 등록 이메일."""
    owner_email = (owner.email or "").strip()
    return bool(getattr(owner, "ops_email_opt_in", False)) and bool(owner_email), owner_email


def _member_ops_sms_target(user: models.User) -> tuple[bool, str | None]:
    sms_ok = bool(
        getattr(user, "ops_sms_opt_in", False)
        and getattr(user, "phone_verified", False)
        and phone_e164_for_sms(getattr(user, "phone_number", None))
    )
    phone = phone_e164_for_sms(getattr(user, "phone_number", None)) if sms_ok else None
    return sms_ok, phone


def _notify_delivery_err_short(exc: BaseException) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    if len(msg) > 100:
        return msg[:97] + "..."
    return msg


def notify_request_owner_new_console_offer(
    *,
    db: Session | None = None,
    request: Any,
    owner: models.User,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> str | None:
    """
    요청 Console에서 새 오퍼 등록 시 요청자에게 이메일·SMS(수신 동의 시).
    부분 실패·미발송 사유가 있으면 컨설턴트용 안내 문구를 반환한다.
    """
    if db is not None and getattr(owner, "id", None):
        fresh = db.query(models.User).filter(models.User.id == int(owner.id)).first()
        if fresh is not None:
            owner = fresh
    email_ok, to_email = _owner_ops_email_channel(owner)
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "new offer notify skipped (no owner channel) owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )
        return "요청자가 업무 이메일·SMS 수신에 동의하지 않았거나 연락처가 없어 알림을 보내지 못했습니다."
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
    sms_body = (
        f"[SAP Dev Hub 오퍼]\n"
        f"{request_title[:50]}\n"
        "컨설턴트가 오퍼했습니다. 로그인 후 요청 상세(제안서)에서 오퍼·프로필을 확인해 주세요."
    )
    warnings: list[str] = []

    if email_ok and to_email:
        try:
            send_plain_notification_email(to_email, subject, body_email)
        except Exception as ex:
            logger.exception(
                "new offer notify email failed owner_id=%s kind=%s rid=%s",
                getattr(owner, "id", None),
                request_kind,
                request_id,
            )
            warnings.append(
                f"요청자 이메일 발송에 실패했습니다. ({_notify_delivery_err_short(ex)})"
            )
    elif to_email and not getattr(owner, "ops_email_opt_in", False):
        warnings.append("요청자가 업무 이메일 수신에 동의하지 않아 이메일은 보내지 않았습니다.")
    elif not to_email:
        warnings.append("요청자 이메일 주소가 없어 이메일은 보내지 않았습니다.")

    if sms_ok and phone_e164:
        try:
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="new_offer")
        except Exception as ex:
            logger.exception(
                "new offer notify sms failed owner_id=%s kind=%s rid=%s",
                getattr(owner, "id", None),
                request_kind,
                request_id,
            )
            warnings.append(
                f"요청자 SMS 발송에 실패했습니다. ({_notify_delivery_err_short(ex)})"
            )

    if not warnings:
        return None
    return " ".join(warnings)


def matched_offer_on_request(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
) -> models.RequestOffer | None:
    """해당 요청에 status=matched 인 오퍼가 있으면 반환(최대 1건 가정)."""
    kind = (request_kind or "").strip().lower()
    return (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.request_kind == kind,
            models.RequestOffer.request_id == int(request_id),
            models.RequestOffer.status == "matched",
        )
        .first()
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


def notify_consultant_request_match_cancelled(
    *,
    request: Any,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> None:
    """요청자가 매칭을 취소했을 때 해당 컨설턴트에게 이메일·SMS(수신 동의 시)."""
    email_ok = bool(getattr(consultant, "ops_email_opt_in", False))
    sms_ok, phone_e164 = _member_ops_sms_target(consultant)
    to_email = (consultant.email or "").strip()
    if email_ok and not to_email:
        email_ok = False
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "match cancel notify skipped (no consultant channel) consultant_id=%s kind=%s rid=%s",
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
    subject = f"[SAP Dev Hub] 매칭 취소 — {request_title[:60]}"
    body_email = (
        "안녕하세요.\n\n"
        "요청자가 귀하와의 매칭을 취소했습니다.\n\n"
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
                f"[SAP Dev Hub 매칭 취소]\n"
                f"{request_title[:45]}\n"
                f"요청자가 매칭을 취소했습니다.\n"
                f"{console_url}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_match_cancel")
    except Exception:
        logger.exception(
            "notify_consultant_request_match_cancelled failed consultant_id=%s kind=%s rid=%s",
            getattr(consultant, "id", None),
            request_kind,
            request_id,
        )


def notify_request_owner_match_cancelled_by_consultant(
    *,
    db: Session | None = None,
    request: Any,
    owner: models.User,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> None:
    """매칭된 컨설턴트가 매칭을 취소했을 때 요청자에게 이메일·SMS(수신 동의 시)."""
    if db is not None and getattr(owner, "id", None):
        fresh = db.query(models.User).filter(models.User.id == int(owner.id)).first()
        if fresh is not None:
            owner = fresh
    email_ok, to_email = _owner_ops_email_channel(owner)
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "match cancel owner notify skipped owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )
        return
    label = inquiry_request_label(
        SimpleNamespace(request_kind=request_kind, request_id=request_id, id=0)
    )
    hub = owner_hub_proposal_public_url(request, request_kind, request_id)
    cname = (getattr(consultant, "full_name", None) or "").strip() or "Consultant"
    subject = f"[SAP Dev Hub] 매칭 취소 — {request_title[:60]}"
    body_email = (
        "안녕하세요.\n\n"
        f"매칭되었던 컨설턴트({cname})가 매칭을 취소했습니다.\n\n"
        f"요청 ID: {label}\n"
        f"요청 제목: {request_title}\n\n"
        f"요청·오퍼 확인:\n{hub}\n"
    )
    try:
        if email_ok and to_email:
            send_plain_notification_email(to_email, subject, body_email)
        if sms_ok and phone_e164:
            sms_body = (
                f"[SAP Dev Hub 매칭 취소]\n"
                f"{request_title[:45]}\n"
                f"컨설턴트가 매칭을 취소했습니다.\n"
                f"{hub}"
            )
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_match_cancel")
    except Exception:
        logger.exception(
            "notify_request_owner_match_cancelled_by_consultant failed owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )


def notify_request_owner_offer_withdrawn(
    *,
    db: Session | None = None,
    request: Any,
    owner: models.User,
    consultant: models.User,
    request_kind: str,
    request_id: int,
    request_title: str,
) -> str | None:
    """컨설턴트가 오퍼를 철회했을 때 요청자에게 이메일·SMS(수신 동의 시)."""
    if db is not None and getattr(owner, "id", None):
        fresh = db.query(models.User).filter(models.User.id == int(owner.id)).first()
        if fresh is not None:
            owner = fresh
    email_ok, to_email = _owner_ops_email_channel(owner)
    sms_ok, phone_e164 = _member_ops_sms_target(owner)
    if not email_ok and not (sms_ok and phone_e164):
        logger.info(
            "offer withdraw notify skipped owner_id=%s kind=%s rid=%s",
            getattr(owner, "id", None),
            request_kind,
            request_id,
        )
        return "요청자가 업무 이메일·SMS 수신에 동의하지 않았거나 연락처가 없어 알림을 보내지 못했습니다."
    hub = owner_hub_proposal_public_url(request, request_kind, request_id)
    label = inquiry_request_label(
        SimpleNamespace(request_kind=request_kind, request_id=request_id, id=0)
    )
    subject = f"[SAP Dev Hub] 오퍼 철회 — {request_title[:60]}"
    body_email = (
        "안녕하세요.\n\n"
        "컨설턴트가 귀하의 요청에 대한 오퍼를 철회했습니다.\n\n"
        f"요청 ID: {label}\n"
        f"요청 제목: {request_title}\n\n"
        f"{consultant_profile_email_lines(consultant)}\n\n"
        f"요청·오퍼 확인:\n{hub}\n"
    )
    sms_body = (
        f"[SAP Dev Hub 오퍼 철회]\n"
        f"{request_title[:50]}\n"
        "컨설턴트가 오퍼를 철회했습니다. 로그인 후 요청 상세에서 확인해 주세요."
    )
    warnings: list[str] = []
    if email_ok and to_email:
        try:
            send_plain_notification_email(to_email, subject, body_email)
        except Exception as ex:
            logger.exception(
                "offer withdraw notify email failed owner_id=%s kind=%s rid=%s",
                getattr(owner, "id", None),
                request_kind,
                request_id,
            )
            warnings.append(
                f"요청자 이메일 발송에 실패했습니다. ({_notify_delivery_err_short(ex)})"
            )
    if sms_ok and phone_e164:
        try:
            send_offer_inquiry_sms(phone_e164, sms_body, sms_type="offer_withdraw")
        except Exception as ex:
            logger.exception(
                "offer withdraw notify sms failed owner_id=%s kind=%s rid=%s",
                getattr(owner, "id", None),
                request_kind,
                request_id,
            )
            warnings.append(
                f"요청자 SMS 발송에 실패했습니다. ({_notify_delivery_err_short(ex)})"
            )
    if not warnings:
        return None
    return " ".join(warnings)


def apply_request_offer_match_action(
    db: Session,
    *,
    http_request: Any,
    offer: models.RequestOffer,
    request_title: str,
    actor: models.User,
    owner_user_id: int,
) -> str | None:
    """
    오퍼 매칭 또는 매칭 취소.
    - 요청자: 매칭 / (납품물 없을 때만) 매칭 취소
    - 매칭된 컨설턴트: 언제든 매칭 취소
    성공 시 None, 실패 시 오류 코드.
    """
    kind = (offer.request_kind or "").strip().lower()
    rid = int(offer.request_id)
    title = (request_title or "").strip() or inquiry_request_label(offer)
    actor_id = int(actor.id)
    owner_id = int(owner_user_id)

    if (offer.status or "").strip() == OFFER_STATUS_MATCHED:
        is_owner = actor_id == owner_id
        is_matched_consultant = actor_id == int(offer.consultant_user_id)
        if not is_owner and not is_matched_consultant:
            return MATCH_ERR_FORBIDDEN
        if is_owner and request_has_deliverables(db, kind, rid):
            return MATCH_ERR_CANCEL_DELIVERABLES
        consultant = offer.consultant
        offer.status = OFFER_STATUS_OFFERED
        offer.matched_at = None
        offer.match_notice_pending = False
        db.add(offer)
        db.commit()
        if consultant:
            if is_owner:
                notify_consultant_request_match_cancelled(
                    request=http_request,
                    consultant=consultant,
                    request_kind=kind,
                    request_id=rid,
                    request_title=title,
                )
            else:
                owner = db.query(models.User).filter(models.User.id == owner_id).first()
                if owner:
                    notify_request_owner_match_cancelled_by_consultant(
                        db=db,
                        request=http_request,
                        owner=owner,
                        consultant=consultant,
                        request_kind=kind,
                        request_id=rid,
                        request_title=title,
                    )
        return None

    if actor_id != owner_id:
        return MATCH_ERR_FORBIDDEN

    if matched_offer_on_request(db, request_kind=kind, request_id=rid) is not None:
        return OFFER_MATCH_ERR_BLOCKED

    offer.status = OFFER_STATUS_MATCHED
    offer.matched_at = datetime.utcnow()
    offer.match_notice_pending = True
    db.add(offer)
    db.commit()
    c = offer.consultant
    if c:
        notify_consultant_request_matched(
            request=http_request,
            consultant=c,
            request_kind=kind,
            request_id=rid,
            request_title=title,
        )
    return None


def withdraw_request_offer(
    db: Session,
    *,
    http_request: Any,
    offer: models.RequestOffer,
    request_title: str,
    actor: models.User,
) -> str | None:
    """컨설턴트 본인 오퍼 철회(status=withdrawn). offered 상태만 가능."""
    if int(actor.id) != int(offer.consultant_user_id):
        return OFFER_ERR_FORBIDDEN
    if (offer.status or "").strip() != OFFER_STATUS_OFFERED:
        return OFFER_ERR_NOT_WITHDRAWABLE
    kind = (offer.request_kind or "").strip().lower()
    rid = int(offer.request_id)
    title = (request_title or "").strip() or inquiry_request_label(offer)
    offer.status = OFFER_STATUS_WITHDRAWN
    offer.matched_at = None
    offer.match_notice_pending = False
    db.add(offer)
    db.commit()
    owner_id = request_owner_user_id(db, kind, rid)
    if owner_id is not None:
        owner = db.query(models.User).filter(models.User.id == owner_id).first()
        consultant = offer.consultant
        if owner and consultant:
            notify_request_owner_offer_withdrawn(
                db=db,
                request=http_request,
                owner=owner,
                consultant=consultant,
                request_kind=kind,
                request_id=rid,
                request_title=title,
            )
    return None


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
        f"문의 내용:\n{body}\n\n"
        f"{console_line}\n"
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
        f"문의 내용:\n{body}\n\n"
        f"{follow_line}\n"
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
        f"답변:\n{body}\n\n"
        f"{follow_line}\n"
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
