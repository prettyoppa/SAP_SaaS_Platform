"""납품 대금 정산 — AI 크레딧·개발코드 생성과 무관."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .bank_transfer_settings import BANK_TRANSFER_SETTING_KEYS
from .project_settlement_settings import (
    fee_amounts_krw,
    format_fee_percent,
    get_platform_fee_bps,
)
from .request_hub_access import request_has_matched_offer
from .request_offer_lifecycle import OFFER_STATUS_MATCHED

PROJECT_SETTLEMENT_PLAN_CODE = "project_settlement"

PAYMENT_METHOD_BANK = "bank_transfer"
PAYMENT_METHOD_PORTONE = "portone"
# 레거시 UI 값
PAYMENT_METHOD_CARD = "card"
_VALID_PAYMENT_METHODS = frozenset({PAYMENT_METHOD_BANK, PAYMENT_METHOD_PORTONE})


def normalize_payment_method(raw: str | None) -> str:
    p = (raw or "").strip().lower()
    if p == PAYMENT_METHOD_CARD:
        return PAYMENT_METHOD_PORTONE
    if p in _VALID_PAYMENT_METHODS:
        return p
    return ""


def _settlement_terms_match(
    settlement: models.ProjectSettlement,
    *,
    gross_amount_krw: int,
    use_platform_payment: bool,
    payment_method: str,
) -> bool:
    gross = max(0, int(gross_amount_krw))
    if int(settlement.gross_amount_krw or 0) != gross:
        return False
    if bool(settlement.use_platform_payment) != bool(use_platform_payment):
        return False
    if use_platform_payment:
        if normalize_payment_method(settlement.payment_method) != normalize_payment_method(payment_method):
            return False
    return True

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
    pm = normalize_payment_method(settlement.payment_method)
    if settlement.use_platform_payment and amount_ok and agreed and pm in _VALID_PAYMENT_METHODS:
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
    bank_settings: dict[str, str] = {}
    if can_view:
        raw = {
            s.key: s.value
            for s in db.query(models.SiteSettings)
            .filter(models.SiteSettings.key.in_(BANK_TRANSFER_SETTING_KEYS))
            .all()
        }
        bank_settings = {k: (raw.get(k) or "").strip() for k in BANK_TRANSFER_SETTING_KEYS}
    pending_bank_claim = None
    if can_view and row.id:
        pending_bank_claim = (
            db.query(models.PaymentClaim)
            .filter(
                models.PaymentClaim.project_settlement_id == int(row.id),
                models.PaymentClaim.status == "pending",
            )
            .order_by(models.PaymentClaim.id.desc())
            .first()
        )
    from .payment_providers.portone_settings import portone_checkout_ready

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
        "settlement_bank_settings": bank_settings,
        "settlement_pending_bank_claim": pending_bank_claim,
        "settlement_portone_ready": portone_checkout_ready(),
        "settlement_payment_method": normalize_payment_method(row.payment_method),
    }


def propose_amount(
    db: Session,
    user: models.User,
    settlement: models.ProjectSettlement,
    *,
    gross_amount_krw: int,
    use_platform_payment: bool,
    payment_method: str | None = "",
) -> str | None:
    if not user_can_view_settlement(db, user, settlement):
        return "forbidden"
    uid = int(user.id)
    if uid not in (int(settlement.owner_user_id), int(settlement.consultant_user_id)):
        return "forbidden"
    gross = max(0, int(gross_amount_krw))
    if use_platform_payment and gross <= 0:
        return "invalid_amount"
    pm = normalize_payment_method(payment_method)
    if use_platform_payment:
        if pm not in _VALID_PAYMENT_METHODS:
            return "invalid_payment_method"
        if pm == PAYMENT_METHOD_PORTONE:
            from .payment_providers.portone_settings import portone_checkout_ready

            if not portone_checkout_ready():
                return "portone_unconfigured"
    else:
        pm = ""
    terms_changed = not _settlement_terms_match(
        settlement,
        gross_amount_krw=gross,
        use_platform_payment=use_platform_payment,
        payment_method=pm,
    )
    bps = get_platform_fee_bps(db)
    fee, payout = fee_amounts_krw(gross, bps) if gross else (0, 0)
    settlement.gross_amount_krw = gross if gross else None
    settlement.platform_fee_rate_bps = bps
    settlement.platform_fee_krw = fee if gross else None
    settlement.consultant_payout_krw = payout if gross else None
    settlement.use_platform_payment = bool(use_platform_payment)
    settlement.payment_method = pm if use_platform_payment else None
    if terms_changed:
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
    if (
        not settlement.gross_amount_krw
        or not settlement.use_platform_payment
        or normalize_payment_method(settlement.payment_method) not in _VALID_PAYMENT_METHODS
    ):
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
    portone_payment_id: str | None = None,
) -> None:
    settlement.funded_at = datetime.utcnow()
    if stripe_session_id:
        settlement.stripe_checkout_session_id = stripe_session_id
    if portone_payment_id:
        settlement.portone_payment_id = (portone_payment_id or "")[:128]
    apply_status(settlement)
    db.add(settlement)


def mark_unfunded(db: Session, settlement: models.ProjectSettlement) -> bool:
    """PortOne 취소 등으로 입금 완료를 되돌림. payable·지급완료면 False."""
    if (settlement.status or "") in (STATUS_PAYABLE, STATUS_PAYOUT_COMPLETED):
        return False
    settlement.funded_at = None
    settlement.portone_payment_id = None
    apply_status(settlement)
    db.add(settlement)
    return True


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
