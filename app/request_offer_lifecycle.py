"""오퍼·매칭 상태 전이(철회, 매칭 취소) 및 납품물 존재 여부."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .delivered_code_package import delivered_package_has_body, parse_delivered_code_payload
from .delivery_fs_supplements import list_delivery_fs_supplements

OFFER_STATUS_OFFERED = "offered"
OFFER_STATUS_MATCHED = "matched"
OFFER_STATUS_WITHDRAWN = "withdrawn"

MATCH_ERR_BLOCKED = "match_blocked"
MATCH_ERR_CANCEL_DELIVERABLES = "match_cancel_deliverables"
MATCH_ERR_FORBIDDEN = "match_forbidden"
OFFER_ERR_NOT_WITHDRAWABLE = "offer_not_withdrawable"
OFFER_ERR_FORBIDDEN = "offer_forbidden"


def request_owner_user_id(db: Session, request_kind: str, request_id: int) -> int | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        uid = db.query(models.RFP.user_id).filter(models.RFP.id == rid).scalar()
    elif kind == "integration":
        uid = db.query(models.IntegrationRequest.user_id).filter(models.IntegrationRequest.id == rid).scalar()
    elif kind == "analysis":
        uid = db.query(models.AbapAnalysisRequest.user_id).filter(models.AbapAnalysisRequest.id == rid).scalar()
    else:
        return None
    return int(uid) if uid is not None else None


def _entity_has_deliverables(db: Session, request_kind: str, row: Any) -> bool:
    """매칭 이후 컨설턴트·플랫폼 납품(FS, 납품 코드 등). 제안은 요청자 산출물이라 제외."""
    if row is None:
        return False
    kind = (request_kind or "").strip().lower()
    rid = int(getattr(row, "id", 0) or 0)
    if (getattr(row, "fs_text", None) or "").strip():
        return True
    if list_delivery_fs_supplements(db, kind, rid):
        return True
    fs_st = (getattr(row, "fs_status", None) or "").strip()
    if fs_st in ("ready", "generating", "failed"):
        return True
    dc_st = (getattr(row, "delivered_code_status", None) or "").strip()
    if dc_st in ("ready", "generating", "failed"):
        return True
    if (getattr(row, "delivered_code_text", None) or "").strip():
        return True
    pkg = parse_delivered_code_payload(getattr(row, "delivered_code_payload", None))
    if delivered_package_has_body(pkg):
        return True
    return False


def request_has_deliverables(db: Session, request_kind: str, request_id: int) -> bool:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        row = db.query(models.RFP).filter(models.RFP.id == rid).first()
    elif kind == "integration":
        row = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == rid).first()
    elif kind == "analysis":
        row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
    else:
        return False
    return _entity_has_deliverables(db, kind, row)


def load_request_row(db: Session, request_kind: str, request_id: int) -> Any | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        return db.query(models.RFP).filter(models.RFP.id == rid).first()
    if kind == "integration":
        return db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == rid).first()
    if kind == "analysis":
        return db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
    return None
