"""납품 대금 정산 — AI 크레딧·개발코드 생성과 무관."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .project_settlement_settings import (
    fee_amounts_krw,
    format_fee_percent,
    get_platform_fee_bps,
)
from .request_hub_access import request_has_matched_offer
from .request_offer_lifecycle import OFFER_STATUS_MATCHED

PROJECT_SETTLEMENT_PLAN_CODE = "project_settlement"

STATUS_OPEN = "open"
STATUS_AWAITING_PAYMENT = "awaiting_payment"
STATUS_FUNDED = "funded"
STATUS_PAYABLE = "payable"
STATUS_PAYOUT_COMPLETED = "payout_completed"
STATUS_CANCELLED = "cancelled"


def normalize_request_kind(raw: str | None) -> str | None:
    k = (raw or "").strip().lower()
    if k in ("rfp", "analysis", "integration"):
        return k
    return None


def _matched_offer(db: Session, *, request_kind: str, request_id: int) -> models.RequestOffer | None:
    return (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id == int(request_id),
            models.RequestOffer.status == OFFER_STATUS_MATCHED,
        )
        .order_by(models.RequestOffer.matched_at.desc())
        .first()
    )


def _load_entity(db: Session, request_kind: str, request_id: int) -> Any | None:
    rid = int(request_id)
    if request_kind == "rfp":
        return db.query(models.RFP).filter(models.RFP.id == rid).first()
    if request_kind == "analysis":
        return (
            db.query(models.AbapAnalysisRequest)
            .filter(models.AbapAnalysisRequest.id == rid)
            .first()
        )
    if request_kind == "integration":
        return (
            db.query(models.IntegrationRequest)
            .filter(models.IntegrationRequest.id == rid)
            .first()
        )
    return None


def user_can_view_settlement(
    db: Session,
    user: models.User | None,
    settlement: models.ProjectSettlement | None,
) -> bool:
    if not user or not settlement:
        return False
    if getattr(user, "is_admin", False):
        return True
    uid = int(user.id)
    return uid in (int(settlement.owner_user_id), int(settlement.consultant_user_id))


def recompute_status(settlement: models.ProjectSettlement) -> str:
    if (settlement.status or "") == STATUS_CANCELLED:
        return STATUS_CANCELLED
    if settlement.payout_completed_at:
        return STATUS_PAYOUT_COMPLETED
    funded = bool(settlement.funded_at)
    req_d = bool(settlement.requester_delivery_confirmed_at)
    con_d = bool(settlement.consultant_delivery_confirmed_at)
    if funded and req_d and con_d:
        return STATUS_PAYABLE
    if funded:
        return STATUS_FUNDED
    amount_ok = bool(settlement.gross_amount_krw and settlement.gross_amount_krw > 0)
    agreed = bool(
        settlement.requester_amount_agreed_at and settlement.consultant_amount_agreed_at
    )
    if settlement.use_platform_payment and amount_ok and agreed:
        return STATUS_AWAITING_PAYMENT
    return STATUS_OPEN


def apply_status(settlement: models.ProjectSettlement) -> None:
    settlement.status = recompute_status(settlement)
    if settlement.status == STATUS_PAYABLE and not settlement.payable_at:
        settlement.payable_at = datetime.utcnow()


def get_or_create_settlement(
    db: Session, *, request_kind: str, request_id: int
) -> models.ProjectSettlement | None:
    kind = normalize_request_kind(request_kind)
    if not kind:
        return None
    rid = int(request_id)
    existing = (
        db.query(models.ProjectSettlement)
        .filter(
            models.ProjectSettlement.request_kind == kind,
            models.ProjectSettlement.request_id == rid,
        )
        .first()
    )
    if existing:
        apply_status(existing)
        return existing
    if not request_has_matched_offer(db, request_kind=kind, request_id=rid):
        return None
    offer = _matched_offer(db, request_kind=kind, request_id=rid)
    entity = _load_entity(db, kind, rid)
    if not offer or not entity:
        return None
    bps = get_platform_fee_bps(db)
    row = models.ProjectSettlement(
        request_kind=kind,
        request_id=rid,
        request_offer_id=int(offer.id),
        owner_user_id=int(entity.user_id),
        consultant_user_id=int(offer.consultant_user_id),
        platform_fee_rate_bps=bps,
        currency="KRW",
        status=STATUS_OPEN,
    )
    db.add(row)
    db.flush()
    return row


def settlement_hub_ctx(
    db: Session,
    user: models.User | None,
    *,
    request_kind: str,
    request_id: int,
    phase_anchor: str,
) -> dict[str, Any]:
    """허브 partial용 컨텍스트."""
    kind = normalize_request_kind(request_kind)
    if not kind or not request_has_matched_offer(db, request_kind=kind, request_id=int(request_id)):
        return {
            "settlement_show_phase": False,
            "settlement_phase_anchor": phase_anchor,
        }
    row = get_or_create_settlement(db, request_kind=kind, request_id=int(request_id))
    if not row:
        return {"settlement_show_phase": False, "settlement_phase_anchor": phase_anchor}
    apply_status(row)
    db.flush()
    can_view = user_can_view_settlement(db, user, row)
    uid = int(user.id) if user else 0
    is_owner = uid == int(row.owner_user_id)
    is_consultant = uid == int(row.consultant_user_id)
    fee_bps = int(row.platform_fee_rate_bps or get_platform_fee_bps(db))
    gross = int(row.gross_amount_krw or 0)
    pf, cp = fee_amounts_krw(gross, fee_bps) if gross else (0, 0)
    profile = None
    if is_consultant and user:
        profile = (
            db.query(models.ConsultantPayoutProfile)
            .filter(
                models.ConsultantPayoutProfile.user_id == uid,
                models.ConsultantPayoutProfile.is_default.is_(True),
            )
            .first()
        )
    return {
        "settlement_show_phase": can_view,
        "settlement_phase_anchor": phase_anchor,
        "settlement": row,
        "settlement_status": row.status,
        "settlement_status_label_ko": status_label_ko(row.status or ""),
        "settlement_status_label_en": status_label_en(row.status or ""),
        "settlement_can_view": can_view,
        "settlement_is_owner": is_owner,
        "settlement_is_consultant": is_consultant,
        "settlement_is_admin": bool(user and user.is_admin),
        "settlement_fee_bps": fee_bps,
        "settlement_fee_percent": format_fee_percent(fee_bps),
        "settlement_platform_fee_krw": pf,
        "settlement_consultant_payout_krw": cp,
        "settlement_gross_display": gross,
        "settlement_profile": profile,
        "settlement_base_path": f"/settlement/{kind}/{int(request_id)}",
        "settlement_request_kind": kind,
    }


def propose_amount(
    db: Session,
    user: models.User,
    settlement: models.ProjectSettlement,
    *,
    gross_amount_krw: int,
    use_platform_payment: bool,
) -> str | None:
    if not user_can_view_settlement(db, user, settlement):
        return "forbidden"
    uid = int(user.id)
    if uid not in (int(settlement.owner_user_id), int(settlement.consultant_user_id)):
        return "forbidden"
    gross = max(0, int(gross_amount_krw))
    if use_platform_payment and gross <= 0:
        return "invalid_amount"
    bps = get_platform_fee_bps(db)
    fee, payout = fee_amounts_krw(gross, bps) if gross else (0, 0)
    settlement.gross_amount_krw = gross if gross else None
    settlement.platform_fee_rate_bps = bps
    settlement.platform_fee_krw = fee if gross else None
    settlement.consultant_payout_krw = payout if gross else None
    settlement.use_platform_payment = bool(use_platform_payment)
    settlement.requester_amount_agreed_at = None
    settlement.consultant_amount_agreed_at = None
    if uid == int(settlement.owner_user_id):
        settlement.requester_amount_agreed_at = datetime.utcnow()
    else:
        settlement.consultant_amount_agreed_at = datetime.utcnow()
    apply_status(settlement)
    db.add(settlement)
    return None


def accept_amount(
    db: Session, user: models.User, settlement: models.ProjectSettlement
) -> str | None:
    if not user_can_view_settlement(db, user, settlement):
        return "forbidden"
    uid = int(user.id)
    if uid == int(settlement.owner_user_id):
        settlement.requester_amount_agreed_at = datetime.utcnow()
    elif uid == int(settlement.consultant_user_id):
        settlement.consultant_amount_agreed_at = datetime.utcnow()
    else:
        return "forbidden"
    if not settlement.gross_amount_krw or not settlement.use_platform_payment:
        return "not_ready"
    apply_status(settlement)
    db.add(settlement)
    return None


def confirm_delivery(
    db: Session, user: models.User, settlement: models.ProjectSettlement
) -> str | None:
    if not user_can_view_settlement(db, user, settlement):
        return "forbidden"
    uid = int(user.id)
    if uid == int(settlement.owner_user_id):
        settlement.requester_delivery_confirmed_at = datetime.utcnow()
    elif uid == int(settlement.consultant_user_id):
        settlement.consultant_delivery_confirmed_at = datetime.utcnow()
    else:
        return "forbidden"
    apply_status(settlement)
    db.add(settlement)
    return None


def mark_funded(
    db: Session,
    settlement: models.ProjectSettlement,
    *,
    stripe_session_id: str | None = None,
) -> None:
    settlement.funded_at = datetime.utcnow()
    if stripe_session_id:
        settlement.stripe_checkout_session_id = stripe_session_id
    apply_status(settlement)
    db.add(settlement)


def mark_payout_completed(
    db: Session,
    admin: models.User,
    settlement: models.ProjectSettlement,
    *,
    note: str = "",
    external_ref: str = "",
) -> str | None:
    if not getattr(admin, "is_admin", False):
        return "forbidden"
    if settlement.status != STATUS_PAYABLE:
        return "not_payable"
    settlement.payout_completed_at = datetime.utcnow()
    settlement.admin_payout_note = (note or "")[:4000]
    settlement.admin_payout_ref = (external_ref or "")[:256]
    apply_status(settlement)
    db.add(settlement)
    return None


def status_label_ko(status: str) -> str:
    return {
        STATUS_OPEN: "진행 중",
        STATUS_AWAITING_PAYMENT: "입금 대기",
        STATUS_FUNDED: "입금 완료",
        STATUS_PAYABLE: "컨설턴트 지급 대기",
        STATUS_PAYOUT_COMPLETED: "지급 완료",
        STATUS_CANCELLED: "취소",
    }.get(status, status)


def status_label_en(status: str) -> str:
    return {
        STATUS_OPEN: "In progress",
        STATUS_AWAITING_PAYMENT: "Awaiting payment",
        STATUS_FUNDED: "Funded",
        STATUS_PAYABLE: "Ready for consultant payout",
        STATUS_PAYOUT_COMPLETED: "Payout completed",
        STATUS_CANCELLED: "Cancelled",
    }.get(status, status)
