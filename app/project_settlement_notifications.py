"""납품 대금 — 계좌이체 신청·입금 완료(계좌/카드) 업무 알림."""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .email_smtp import send_plain_notification_email
from .offer_inquiry_service import _member_ops_sms_target, _owner_ops_email_channel
from .project_settlement import _load_entity, normalize_request_kind
from .sms_sender import send_offer_inquiry_sms
from .wallet_topup_notifications import (
    ADMIN_LABEL_KO,
    _member_wallet_email,
    _member_wallet_sms,
    _notify_admins,
    schedule_wallet_notification,
)

logger = logging.getLogger(__name__)

FundedSource = Literal["bank", "portone"]


def schedule_settlement_notification(fn, *args, **kwargs) -> None:
    schedule_wallet_notification(fn, *args, **kwargs)


def _format_krw(amount: int) -> str:
    return f"₩{int(amount):,}"


def _request_kind_label_ko(kind: str) -> str:
    labels = {"rfp": "신규 개발(RFP)", "analysis": "분석·개선", "integration": "연동 개발"}
    return labels.get((kind or "").strip().lower(), kind or "요청")


def _settlement_hub_path(settlement: models.ProjectSettlement) -> str:
    kind = normalize_request_kind(settlement.request_kind) or "rfp"
    rid = int(settlement.request_id)
    if kind == "analysis":
        return f"/abap-analysis/{rid}?phase=settlement#abap-phase-settlement"
    if kind == "integration":
        return f"/integration/{rid}?phase=settlement#int-phase-settlement"
    return f"/rfp/{rid}?phase=settlement#rfp-phase-settlement"


def _request_title(db: Session, settlement: models.ProjectSettlement) -> str:
    entity = _load_entity(db, settlement.request_kind, int(settlement.request_id))
    if not entity:
        return f"요청 #{settlement.request_id}"
    for attr in ("title", "subject", "name"):
        raw = (getattr(entity, attr, None) or "").strip()
        if raw:
            return raw[:200]
    return f"요청 #{settlement.request_id}"


def _member_display(user: models.User | None) -> str:
    if not user:
        return "회원"
    return (user.full_name or "").strip() or (user.email or "").strip() or "회원"


def _member_account_email(user: models.User | None) -> str:
    """알림 본문 — 의뢰자·컨설턴트 식별은 계정 이메일 우선."""
    if not user:
        return "(이메일 없음)"
    return (user.email or "").strip() or "(이메일 없음)"


def _notify_member_ops(
    user: models.User,
    *,
    subject: str,
    email_body: str,
    sms_body: str,
    sms_type: str,
) -> None:
    """회원(컨설턴트) — 업무 이메일·SMS 수신 동의 시에만 발송."""
    try:
        email_ok, addr = _owner_ops_email_channel(user)
        if email_ok and addr:
            send_plain_notification_email(addr, subject, email_body)
    except Exception:
        logger.exception("settlement member notify email failed user_id=%s", user.id)
    try:
        sms_ok, phone = _member_ops_sms_target(user)
        if sms_ok and phone:
            send_offer_inquiry_sms(phone, sms_body, sms_type=sms_type)
    except Exception:
        logger.exception("settlement member notify sms failed user_id=%s", user.id)


def _notify_member_transactional(
    user: models.User,
    *,
    subject: str,
    email_body: str,
    sms_body: str,
    sms_type: str,
) -> None:
    """신청 회원 — 가입 이메일·인증 휴대폰(또는 업무 SMS 동의)으로 거래성 알림."""
    try:
        ok, addr = _member_wallet_email(user)
        if ok and addr:
            send_plain_notification_email(addr, subject, email_body)
    except Exception:
        logger.exception("settlement member transactional email failed user_id=%s", user.id)
    try:
        sms_ok, phone = _member_wallet_sms(user)
        if sms_ok and phone:
            send_offer_inquiry_sms(phone, sms_body, sms_type=sms_type)
    except Exception:
        logger.exception("settlement member transactional sms failed user_id=%s", user.id)


def notify_member_settlement_bank_confirmed(
    db: Session,
    claim: models.PaymentClaim,
    settlement: models.ProjectSettlement,
    member: models.User,
) -> None:
    """관리자가 납품 대금 계좌이체 입금 신청을 확인했을 때 신청 회원(의뢰자) 알림."""
    title = _request_title(db, settlement)
    hub = _settlement_hub_path(settlement)
    requested = int(claim.amount_minor)
    confirmed = int(
        claim.confirmed_amount_minor if claim.confirmed_amount_minor is not None else requested
    )
    subject = "[SAP Dev Hub] 납품 대금 입금 확인 안내"
    email_body = (
        f"안녕하세요, {_member_display(member)}님.\n\n"
        f"납품 대금 계좌이체 입금 신청에 대해 {ADMIN_LABEL_KO}가 확인했습니다.\n\n"
        f"요청: {title}\n"
        f"신청 금액: {_format_krw(requested)}\n"
        f"확인 금액: {_format_krw(confirmed)}\n\n"
        f"허브 납품·대금 단계에서 상태를 확인할 수 있습니다.\n"
        f"{hub}"
    )
    sms_body = (
        f"[SAP Dev Hub 납품대금]\n"
        f"{ADMIN_LABEL_KO} 입금 확인 {_format_krw(confirmed)}\n"
        f"{title[:40]}"
    )
    _notify_member_transactional(
        member,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="settlement_bank_member_confirmed",
    )


def notify_admins_settlement_bank_claim_submitted(
    db: Session,
    claim: models.PaymentClaim,
    settlement: models.ProjectSettlement,
    owner: models.User,
    consultant: models.User,
) -> None:
    title = _request_title(db, settlement)
    kind_ko = _request_kind_label_ko(settlement.request_kind)
    owner_id = _member_account_email(owner)
    consultant_id = _member_account_email(consultant)
    amt = int(claim.amount_minor)
    subject = "[SAP Dev Hub] 납품 대금 계좌이체 입금 신청"
    email_body = (
        f"의뢰자가 납품 대금 계좌이체 입금을 신청했습니다.\n\n"
        f"요청: {title} ({kind_ko})\n"
        f"정산 #{settlement.id}\n"
        f"의뢰자 계정: {owner_id}\n"
        f"컨설턴트 계정: {consultant_id}\n"
        f"신청 금액: {_format_krw(amt)}\n"
        f"입금자명: {(claim.depositor_name or '').strip()}\n"
        f"신청 번호: #{claim.id}\n\n"
        "관리자 화면 「입금 신청 (계좌이체)」에서 확인·승인해 주세요."
    )
    sms_body = (
        f"[SAP Dev Hub 납품대금]\n"
        f"{owner_id} 입금신청 {_format_krw(amt)}\n"
        f"정산 #{settlement.id} — 관리자 확인 필요"
    )
    _notify_admins(
        db,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="settlement_bank_admin",
    )


def notify_consultant_settlement_bank_claim_submitted(
    db: Session,
    claim: models.PaymentClaim,
    settlement: models.ProjectSettlement,
    owner: models.User,
    consultant: models.User,
) -> None:
    title = _request_title(db, settlement)
    owner_id = _member_account_email(owner)
    amt = int(claim.amount_minor)
    hub = _settlement_hub_path(settlement)
    subject = "[SAP Dev Hub] 납품 대금 계좌이체 입금 신청 알림"
    email_body = (
        f"안녕하세요, {_member_display(consultant)}님.\n\n"
        f"매칭된 프로젝트에서 의뢰자가 납품 대금 계좌이체 입금을 신청했습니다.\n\n"
        f"요청: {title}\n"
        f"의뢰자 계정: {owner_id}\n"
        f"신청 금액: {_format_krw(amt)}\n"
        f"입금자명: {(claim.depositor_name or '').strip()}\n\n"
        f"관리자 입금 확인 후 정산 상태가 갱신됩니다.\n"
        f"허브 납품·대금: {hub}"
    )
    sms_body = (
        f"[SAP Dev Hub 납품대금]\n"
        f"{owner_id} 계좌이체 신청 {_format_krw(amt)}\n"
        f"관리자 확인 후 반영 — {title[:40]}"
    )
    _notify_member_ops(
        consultant,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="settlement_bank_consultant",
    )


def notify_consultant_settlement_funded(
    db: Session,
    settlement: models.ProjectSettlement,
    owner: models.User,
    consultant: models.User,
    *,
    source: FundedSource,
) -> None:
    title = _request_title(db, settlement)
    gross = int(settlement.gross_amount_krw or 0)
    payout = int(settlement.consultant_payout_krw or 0)
    hub = _settlement_hub_path(settlement)
    if source == "portone":
        pay_ko = "카드·온라인 결제(PortOne)"
        pay_en_hint = "online payment"
    else:
        pay_ko = "계좌이체(관리자 입금 확인)"
        pay_en_hint = "bank transfer confirmed"
    subject = "[SAP Dev Hub] 납품 대금 입금 완료"
    email_body = (
        f"안녕하세요, {_member_display(consultant)}님.\n\n"
        f"매칭된 프로젝트의 납품 대금 입금이 확인되었습니다.\n\n"
        f"요청: {title}\n"
        f"의뢰자 계정: {_member_account_email(owner)}\n"
        f"입금 수단: {pay_ko}\n"
        f"합의 대금: {_format_krw(gross)}\n"
        f"컨설턴트 지급 예정: {_format_krw(payout)}\n\n"
        f"허브에서 납품·대금 단계를 확인하세요.\n"
        f"{hub}\n\n"
        f"({pay_en_hint})"
    )
    sms_body = (
        f"[SAP Dev Hub 납품대금]\n"
        f"입금완료 {_format_krw(gross)}\n"
        f"지급예정 {_format_krw(payout)} — {title[:36]}"
    )
    _notify_member_ops(
        consultant,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="settlement_funded_consultant",
    )


def notify_admins_settlement_funded_online(
    db: Session,
    settlement: models.ProjectSettlement,
    owner: models.User,
    consultant: models.User,
) -> None:
    """카드(PortOne) 결제 완료 — 관리자 참고 알림."""
    title = _request_title(db, settlement)
    gross = int(settlement.gross_amount_krw or 0)
    subject = "[SAP Dev Hub] 납품 대금 온라인 결제 완료"
    email_body = (
        f"납품 대금이 PortOne 온라인 결제로 입금되었습니다.\n\n"
        f"요청: {title}\n"
        f"정산 #{settlement.id}\n"
        f"의뢰자 계정: {_member_account_email(owner)}\n"
        f"컨설턴트 계정: {_member_account_email(consultant)}\n"
        f"입금액: {_format_krw(gross)}\n\n"
        "관리자 「납품 대금 정산」에서 상태를 확인할 수 있습니다."
    )
    sms_body = (
        f"[SAP Dev Hub 납품대금]\n"
        f"온라인결제 완료 {_format_krw(gross)}\n"
        f"정산 #{settlement.id}"
    )
    _notify_admins(
        db,
        subject=subject,
        email_body=email_body,
        sms_body=sms_body,
        sms_type="settlement_funded_admin",
    )


def job_notify_settlement_bank_submitted(claim_id: int) -> None:
    db = SessionLocal()
    try:
        claim = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
        if not claim or not claim.project_settlement_id:
            return
        settlement = (
            db.query(models.ProjectSettlement)
            .filter(models.ProjectSettlement.id == int(claim.project_settlement_id))
            .first()
        )
        if not settlement:
            return
        owner = db.query(models.User).filter(models.User.id == int(settlement.owner_user_id)).first()
        consultant = (
            db.query(models.User).filter(models.User.id == int(settlement.consultant_user_id)).first()
        )
        if not owner or not consultant:
            return
        notify_admins_settlement_bank_claim_submitted(db, claim, settlement, owner, consultant)
        notify_consultant_settlement_bank_claim_submitted(db, claim, settlement, owner, consultant)
    finally:
        db.close()


def job_notify_settlement_funded(settlement_id: int, source: str) -> None:
    if source not in ("bank", "portone"):
        return
    db = SessionLocal()
    try:
        settlement = (
            db.query(models.ProjectSettlement)
            .filter(models.ProjectSettlement.id == int(settlement_id))
            .first()
        )
        if not settlement or not settlement.funded_at:
            return
        owner = db.query(models.User).filter(models.User.id == int(settlement.owner_user_id)).first()
        consultant = (
            db.query(models.User).filter(models.User.id == int(settlement.consultant_user_id)).first()
        )
        if not owner or not consultant:
            return
        src: FundedSource = "portone" if source == "portone" else "bank"
        notify_consultant_settlement_funded(db, settlement, owner, consultant, source=src)
        if src == "portone":
            notify_admins_settlement_funded_online(db, settlement, owner, consultant)
    finally:
        db.close()


def job_notify_member_settlement_bank_confirmed(claim_id: int) -> None:
    db = SessionLocal()
    try:
        claim = db.query(models.PaymentClaim).filter(models.PaymentClaim.id == int(claim_id)).first()
        if not claim or not claim.project_settlement_id or (claim.status or "") != "confirmed":
            return
        settlement = (
            db.query(models.ProjectSettlement)
            .filter(models.ProjectSettlement.id == int(claim.project_settlement_id))
            .first()
        )
        if not settlement:
            return
        member = db.query(models.User).filter(models.User.id == int(claim.user_id)).first()
        if not member:
            return
        notify_member_settlement_bank_confirmed(db, claim, settlement, member)
    finally:
        db.close()
