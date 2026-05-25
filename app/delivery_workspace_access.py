"""납품 ABAP 구현 보완 작업실 — 접근(컨설턴트·자가 요청·관리자만)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from .delivered_code_package import (
    delivered_package_has_body,
    integration_delivered_package_has_body,
    parse_delivered_code_payload,
    parse_integration_delivered_payload,
)
from .request_hub_access import consultant_is_matched_on_request


def _entity_delivered_ready(row: Any) -> bool:
    return (getattr(row, "delivered_code_status", None) or "").strip() == "ready"


def official_package_has_body(row: Any, request_kind: str) -> bool:
    kind = (request_kind or "").strip().lower()
    if kind == KIND_INTEGRATION:
        return integration_delivered_package_has_body(
            parse_integration_delivered_payload(getattr(row, "delivered_code_payload", None))
        )
    return delivered_package_has_body(
        parse_delivered_code_payload(getattr(row, "delivered_code_payload", None))
    )


def user_can_use_delivery_workspace(
    db: Session,
    user: Any | None,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None = None,
) -> bool:
    """
    ABAP 구현 보완 작업실 — 일반 요청자(비컨설턴트) 비노출.
    규칙 X: 컨설턴트이면서 본인 요청 owner이고 납품 ready → 매칭 없이 허용.
    그 외: 관리자 또는 해당 요청 매칭 컨설턴트.
    """
    if not user:
        return False
    row = entity
    if row is None:
        from .delivery_workspace import load_request_row

        row = load_request_row(db, request_kind=request_kind, request_id=request_id)
    if not row:
        return False
    try:
        if int(getattr(row, "user_id", 0) or 0) != int(owner_user_id):
            return False
    except (TypeError, ValueError):
        return False
    if not _entity_delivered_ready(row):
        return False
    if not official_package_has_body(row, request_kind):
        return False
    if getattr(user, "is_admin", False):
        return True
    if not getattr(user, "is_consultant", False):
        return False
    try:
        uid = int(user.id)
        owner = int(owner_user_id)
    except (TypeError, ValueError):
        return False
    if uid == owner:
        return True
    return consultant_is_matched_on_request(
        db,
        consultant_user_id=uid,
        request_kind=request_kind,
        request_id=int(request_id),
    )


def delivery_workspace_path(request_kind: str, request_id: int) -> str:
    kind = (request_kind or "").strip().lower()
    return f"/delivery/{kind}/{int(request_id)}/workspace"


def apply_hub_delivery_workspace_ctx(
    ctx: dict,
    *,
    db: Session,
    user: Any | None,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None = None,
) -> None:
    can = user_can_use_delivery_workspace(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    )
    ctx["can_use_delivery_workspace"] = can
    ctx["delivery_workspace_url"] = (
        delivery_workspace_path(request_kind, request_id) if can else ""
    )
