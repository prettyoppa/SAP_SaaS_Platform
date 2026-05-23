"""요청자 「개발 의뢰하기」 — 컨설턴트 오퍼·FS 파이프라인 게이트 (AI 크레딧, Stripe 아님)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .ai_wallet import apply_wallet_debit, wallet_balance_krw
from .delivery_proposal_supplements import (
    KIND_ANALYSIS,
    KIND_INTEGRATION,
    KIND_RFP,
    has_delivery_proposal_supplements,
)
from .paid_tier import PAID_ACTIVE, paid_engagement_is_active

DEV_ENGAGEMENT_KRW_KEY = "dev_engagement_krw"


def dev_engagement_price_krw(db: Session) -> int:
    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == DEV_ENGAGEMENT_KRW_KEY)
        .first()
    )
    raw = (row.value if row else "") or "0"
    try:
        n = int(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def _entity_paid_status(entity: Any) -> str:
    return (getattr(entity, "paid_engagement_status", None) or "none").strip()


def request_engagement_is_active(entity: Any | None) -> bool:
    if entity is None:
        return False
    if isinstance(entity, models.RFP):
        return paid_engagement_is_active(entity)
    return _entity_paid_status(entity) == PAID_ACTIVE


def load_engagement_entity(
    db: Session, request_kind: str, request_id: int
) -> models.RFP | models.IntegrationRequest | models.AbapAnalysisRequest | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        return db.query(models.RFP).filter(models.RFP.id == rid).first()
    if kind == "integration":
        return (
            db.query(models.IntegrationRequest)
            .filter(models.IntegrationRequest.id == rid)
            .first()
        )
    if kind == "analysis":
        return (
            db.query(models.AbapAnalysisRequest)
            .filter(models.AbapAnalysisRequest.id == rid)
            .first()
        )
    return None


def _kind_for_entity(entity: Any) -> str:
    if isinstance(entity, models.RFP):
        return "rfp"
    if isinstance(entity, models.IntegrationRequest):
        return "integration"
    if isinstance(entity, models.AbapAnalysisRequest):
        return "analysis"
    return ""


def _owner_user_id(entity: Any) -> int:
    return int(getattr(entity, "user_id", 0) or 0)


def request_has_publishable_proposal(db: Session, entity: Any) -> bool:
    if (getattr(entity, "proposal_text", None) or "").strip():
        return True
    kind = _kind_for_entity(entity)
    if not kind:
        return False
    rid = int(getattr(entity, "id", 0) or 0)
    if kind == "rfp":
        return has_delivery_proposal_supplements(db, KIND_RFP, rid)
    if kind == "integration":
        return has_delivery_proposal_supplements(db, KIND_INTEGRATION, rid)
    if kind == "analysis":
        return has_delivery_proposal_supplements(db, KIND_ANALYSIS, rid)
    return False


def request_engagement_accepts_offers(db: Session, request_kind: str, request_id: int) -> bool:
    entity = load_engagement_entity(db, request_kind, request_id)
    return request_engagement_is_active(entity)


def can_activate_request_engagement(
    db: Session, user: models.User | None, entity: Any
) -> bool:
    if not user or not entity:
        return False
    if int(user.id) != _owner_user_id(entity):
        return False
    if request_engagement_is_active(entity):
        return False
    st = _entity_paid_status(entity)
    if st == "cancelled":
        return False
    if not request_has_publishable_proposal(db, entity):
        return False
    return True


def activate_request_engagement(
    db: Session, user: models.User, request_kind: str, request_id: int
) -> str | None:
    """
    개발 의뢰 활성화. 성공 시 None, 실패 시 안정적인 오류 코드(쿼리 engagement_err).
  """
    entity = load_engagement_entity(db, request_kind, request_id)
    if not entity:
        return "not_found"
    if int(user.id) != _owner_user_id(entity):
        return "forbidden"
    if request_engagement_is_active(entity):
        return "already_active"
    if not request_has_publishable_proposal(db, entity):
        return "no_proposal"
    price = dev_engagement_price_krw(db)
    if price > 0 and wallet_balance_krw(user) < price:
        return "wallet_insufficient"
    if price > 0:
        apply_wallet_debit(user, price)
    entity.paid_engagement_status = PAID_ACTIVE
    if hasattr(entity, "paid_activated_at"):
        entity.paid_activated_at = datetime.utcnow()
    db.add(entity)
    db.add(user)
    db.commit()
    return None


def engagement_flash_message(code: str | None) -> dict[str, str] | None:
    """bilingual flash via i18n key or inline ko/en in template."""
    key = (code or "").strip()
    if not key:
        return None
    mapping: dict[str, tuple[str, str]] = {
        "ok": (
            "개발 의뢰가 활성화되었습니다. 컨설턴트가 오퍼를 제안할 수 있습니다.",
            "Your development request is open. Consultants may submit offers.",
        ),
        "wallet_insufficient": (
            "AI 크레딧 잔액이 부족합니다. 계정 메뉴에서 충전한 뒤 다시 시도해 주세요.",
            "Insufficient AI credit balance. Top up in Account, then try again.",
        ),
        "no_proposal": (
            "개발 제안서를 확인·생성한 뒤 개발 의뢰하기를 이용할 수 있습니다.",
            "Generate or review the development proposal before opening for offers.",
        ),
        "already_active": (
            "이미 개발 의뢰가 활성화되어 있습니다.",
            "Development request is already open.",
        ),
        "forbidden": (
            "요청 소유자만 개발 의뢰하기를 할 수 있습니다.",
            "Only the request owner can open a development request.",
        ),
        "not_found": (
            "요청을 찾을 수 없습니다.",
            "Request not found.",
        ),
    }
    pair = mapping.get(key)
    if not pair:
        return None
    return {"ko": pair[0], "en": pair[1]}


def request_engagement_hub_ctx(
    db: Session,
    user: models.User | None,
    entity: Any,
    *,
    activate_url: str,
) -> dict[str, Any]:
    active = request_engagement_is_active(entity)
    price = dev_engagement_price_krw(db)
    can = bool(not active and can_activate_request_engagement(db, user, entity))
    bal = wallet_balance_krw(user) if user else 0
    return {
        "paid_engagement_active": active,
        "can_activate_dev_engagement": can,
        "dev_engagement_price_krw": price,
        "wallet_balance_krw": bal,
        "dev_engagement_activate_url": activate_url,
        "dev_engagement_wallet_short": bool(
            can and price > 0 and bal < price
        ),
    }
