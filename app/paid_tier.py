"""유료 개발 의뢰(FS·납품 코드) 공통 헬퍼."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from . import models


class _UserLike(Protocol):
    is_admin: bool
    is_consultant: bool


PAID_ACTIVE = "active"


def paid_engagement_is_active(rfp: models.RFP) -> bool:
    return (getattr(rfp, "paid_engagement_status", None) or "none").strip() == PAID_ACTIVE


def paid_delivery_pipeline_started(rfp: models.RFP) -> bool:
    """FS·납품 코드 생성이 한 번이라도 건드려진 경우(testing / post-payment)."""
    fs_s = (getattr(rfp, "fs_status", None) or "none").strip()
    dc_s = (getattr(rfp, "delivered_code_status", None) or "none").strip()
    return fs_s != "none" or dc_s != "none"


def user_can_access_fs_hub(
    user: _UserLike | None,
    rfp: models.RFP,
    *,
    db: Session | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> bool:
    """
    FS/납품 조회·다운로드 허용.

    - 결제 활성이면 항상.
    - 관리자는 결제 여부와 무관하게 조회.
    - 소유자: 미결제여도 납품 파이프라인이 시작됐으면 조회.
    - 컨설턴트: 해당 요청에 매칭(matched)된 경우만 (db·request_kind·request_id 필요).
    """
    if not user:
        return False
    if paid_engagement_is_active(rfp):
        return True
    if getattr(user, "is_admin", False):
        return True
    try:
        owner_id = int(getattr(rfp, "user_id", 0) or 0)
        uid = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        owner_id = 0
        uid = 0
    if uid and uid == owner_id:
        return paid_delivery_pipeline_started(rfp)
    if getattr(user, "is_consultant", False):
        if db is None:
            return False
        from .request_hub_access import user_can_view_request_deliverables

        kind = (request_kind or "rfp").strip().lower()
        rid = int(request_id if request_id is not None else getattr(rfp, "id", 0) or 0)
        return user_can_view_request_deliverables(
            db,
            user,
            request_kind=kind,
            request_id=rid,
            owner_user_id=owner_id,
            paid_entity=rfp,
        )
    return paid_delivery_pipeline_started(rfp)


def user_can_operate_delivery(user: _UserLike | None) -> bool:
    """FS·납품 코드 생성/관리 권한: admin 또는 consultant."""
    if not user:
        return False
    return bool(getattr(user, "is_admin", False) or getattr(user, "is_consultant", False))


def rfp_eligible_for_stripe_checkout(rfp: models.RFP, *, has_proposal_supplements: bool = False) -> bool:
    if not ((rfp.proposal_text or "").strip()) and not has_proposal_supplements:
        return False
    if paid_engagement_is_active(rfp):
        return False
    st = (getattr(rfp, "paid_engagement_status", None) or "none").strip()
    if st == "cancelled":
        return False
    return True


def rfp_summary_for_paid(rfp: models.RFP) -> dict[str, Any]:
    return {
        "title": rfp.title,
        "program_id": ((getattr(rfp, "program_id", None) or "").strip() or None),
        "transaction_code": ((getattr(rfp, "transaction_code", None) or "").strip() or None),
        "sap_modules": [x.strip() for x in (rfp.sap_modules or "").split(",") if x.strip()]
        if rfp.sap_modules
        else [],
        "dev_types": [x.strip() for x in (rfp.dev_types or "").split(",") if x.strip()]
        if rfp.dev_types
        else [],
        "description": (rfp.description or "")[:8000],
    }
