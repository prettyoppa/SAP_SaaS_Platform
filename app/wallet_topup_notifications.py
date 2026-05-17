"""AI 크레딧 충전·회원가입 — 관리자/회원 업무 알림(이메일·SMS, 수신 동의)."""

from __future__ import annotations

import logging
import threading
from typing import Literal

from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .email_smtp import send_plain_notification_email
from .offer_inquiry_service import _member_ops_sms_target, _owner_ops_email_channel, phone_e164_for_sms
from .sms_sender import send_offer_inquiry_sms

logger = logging.getLogger(__name__)

ADMIN_LABEL_KO = "관리자"
ADMIN_LABEL_EN = "Admin"


def schedule_wallet_notification(fn, *args, **kwargs) -> None:
    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("wallet notification failed (%s)", getattr(fn, "__name__", repr(fn)))

    threading.Thread(target=_run, daemon=True).start()


def _format_krw(amount: int) -> str:
    return f"₩{int(amount):,}"


def _admin_ops_recipients(db: Session) -> list[models.User]:
    return (
        db.query(models.User)
        .filter(
            models.User.is_admin.is_(True),
            models.User.is_active.is_(True),
        )
        .all()
    )


def _send_ops_email(user: models.User, subject: str, body: str) -> None:
    ok, addr = _owner_ops_email_channel(user)
    if not ok or not addr:
        return
    send_plain_notification_email(addr, subject, body)


def _send_ops_sms(user: models.User, body: str, *, sms_type: str) -> None:
    sms_ok, phone = _member_ops_sms_target(user)
    if sms_ok and phone:
        send_offer_inquiry_sms(phone, body, sms_type=sms_type)


def _notify_admins(
    db: Session,
    *,
    subject: str,
    email_body: str,
    sms_body: str,
    sms_type: str,
) -> None:
    for admin in _admin_ops_recipients(db):
        try:
            _send_ops_email(admin, subject, email_body)
        except Exception:
            logger.exception("admin notify email failed admin_id=%s", admin.id)
        try:
            _send_ops_sms(admin, sms_body, sms_type=sms_type)
        except Exception:
            logger.exception("admin notify sms failed admin_id=%s", admin.id)


def _member_account_type_label(user: models.User) -> str:
    if getattr(user, "consultant_application_pending", False):
        return "컨설턴트 가입 신청"
    if getattr(user, "is_consultant", False):
        return "컨설턴트"
    return "일반 회원"


def notify_admins_wallet_topup_submitted(db: Session, claim: models.PaymentClaim, member: models.User) -> None:
    """회원이 충전 확인(신청) 제출 시 관리자에게 알림."""
    name = (member.full_name or "").strip() or member.email
    amt = int(claim.amount_minor)
    subject = "[SAP Dev Hub] AI 크레딧 충전 신청"
    email_body = (
        f"회원 {name}님이 AI 크레딧 충전을 신청했습니다.\n\n"
        f"회원 이름: {name}\n"
        f"신청 금액: {_format_krw(amt)}\n"
        f"입금자명: {(claim.depositor_name or '').strip()}\n"
        f"신청 번호: #{claim.id}\n\n"
        "관리자 화면의 입금 신청 대기열에서 확인해 주세요."
    )
    sms_body = (
        f"[SAP Dev Hub 충전신청]\n"
        f"{name} / {_format_krw(amt)}\n"
        f"신청 #{claim.id} — 관리자 확인 필요"
    )
    _notify_admins(
        db,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="wallet_topup_admin",
    )


def notify_member_wallet_topup_reviewed(
    db: Session,
    claim: models.PaymentClaim,
    member: models.User,
    *,
    action: Literal["confirmed", "rejected"],
) -> None:
    """관리자 확인·반려 시 신청 회원에게 알림."""
    name = (member.full_name or "").strip() or "회원"
    requested = int(claim.amount_minor)
    if action == "confirmed":
        action_ko = "확인"
        action_amount = int(
            claim.confirmed_amount_minor
            if claim.confirmed_amount_minor is not None
            else requested
        )
    else:
        action_ko = "반려"
        action_amount = 0

    subject = f"[SAP Dev Hub] 충전 신청 {action_ko} 안내"
    email_body = (
        f"안녕하세요, {name}님.\n\n"
        f"AI 크레딧 충전 신청에 대해 {ADMIN_LABEL_KO}가 처리했습니다.\n\n"
        f"회원 이름: {name}\n"
        f"신청 금액: {_format_krw(requested)}\n"
        f"처리: {action_ko}\n"
        f"{action_ko} 금액: {_format_krw(action_amount)}\n\n"
        "자세한 내용은 사용량 · 충전 화면에서 확인할 수 있습니다."
    )
    sms_body = (
        f"[SAP Dev Hub 충전]\n"
        f"{name}님 신청 {_format_krw(requested)}\n"
        f"{ADMIN_LABEL_KO} {action_ko} {_format_krw(action_amount)}"
    )

    try:
        ok, addr = _owner_ops_email_channel(member)
        if ok and addr:
            send_plain_notification_email(addr, subject, email_body)
    except Exception:
        logger.exception("member topup notify email failed user_id=%s claim_id=%s", member.id, claim.id)

    try:
        sms_ok, phone = _member_ops_sms_target(member)
        if sms_ok and phone:
            send_offer_inquiry_sms(phone, sms_body, sms_type=f"wallet_topup_{action}")
    except Exception:
        logger.exception("member topup notify sms failed user_id=%s claim_id=%s", member.id, claim.id)


def notify_admins_new_registration(db: Session, user: models.User) -> None:
    """회원가입 완료 시 관리자에게 알림."""
    name = (user.full_name or "").strip() or user.email
    kind = _member_account_type_label(user)
    subject = "[SAP Dev Hub] 신규 회원 가입"
    email_body = (
        f"신규 회원이 가입했습니다.\n\n"
        f"이름: {name}\n"
        f"이메일: {user.email}\n"
        f"구분: {kind}\n"
    )
    if user.company:
        email_body += f"소속: {user.company}\n"
    email_body += "\n관리자 회원 목록에서 확인할 수 있습니다."
    sms_body = f"[SAP Dev Hub 가입]\n{name} ({kind})"
    _notify_admins(
        db,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="member_register_admin",
    )


def job_notify_admins_wallet_topup_submitted(claim_id: int) -> None:
    db = SessionLocal()
    try:
        claim = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
        if not claim:
            return
        member = db.query(models.User).filter(models.User.id == int(claim.user_id)).first()
        if not member:
            return
        notify_admins_wallet_topup_submitted(db, claim, member)
    finally:
        db.close()


def job_notify_member_wallet_topup_reviewed(claim_id: int, action: str) -> None:
    if action not in ("confirmed", "rejected"):
        return
    db = SessionLocal()
    try:
        claim = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
        if not claim:
            return
        member = db.query(models.User).filter(models.User.id == int(claim.user_id)).first()
        if not member:
            return
        notify_member_wallet_topup_reviewed(db, claim, member, action=action)  # type: ignore[arg-type]
    finally:
        db.close()


def job_notify_admins_new_registration(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
        if not user:
            return
        notify_admins_new_registration(db, user)
    finally:
        db.close()
