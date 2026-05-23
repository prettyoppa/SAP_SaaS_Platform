"""요청자 「개발 의뢰하기」 — 컨설턴트 오퍼 게이트 (무료, AI 크레딧 차감 없음)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .delivery_proposal_supplements import (
    KIND_ANALYSIS,
    KIND_INTEGRATION,
    KIND_RFP,
    has_delivery_proposal_supplements,
)
from .paid_tier import PAID_ACTIVE, paid_engagement_is_active


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
    """개발 의뢰 활성화(무료). 성공 시 None, 실패 시 engagement_err 코드."""
    entity = load_engagement_entity(db, request_kind, request_id)
    if not entity:
        return "not_found"
    if int(user.id) != _owner_user_id(entity):
        return "forbidden"
    if request_engagement_is_active(entity):
        return "already_active"
    if not request_has_publishable_proposal(db, entity):
        return "no_proposal"
    entity.paid_engagement_status = PAID_ACTIVE
    if hasattr(entity, "paid_activated_at"):
        entity.paid_activated_at = datetime.utcnow()
    db.add(entity)
    db.commit()
    return None


def engagement_flash_message(code: str | None) -> dict[str, str] | None:
    key = (code or "").strip()
    if not key:
        return None
    mapping: dict[str, tuple[str, str]] = {
        "ok": (
            "개발 의뢰가 활성화되었습니다. 전문가 그룹이 오퍼를 제안할 수 있습니다.",
            "Your development request is open. Our expert group may submit offers.",
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
    can = bool(not active and can_activate_request_engagement(db, user, entity))
    return {
        "paid_engagement_active": active,
        "can_activate_dev_engagement": can,
        "dev_engagement_activate_url": activate_url,
    }
