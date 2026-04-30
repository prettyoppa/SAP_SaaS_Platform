"""유료 개발 의뢰(FS·납품 코드) 공통 헬퍼."""

from __future__ import annotations

from typing import Any, Protocol

from . import models


class _UserLike(Protocol):
    is_admin: bool


PAID_ACTIVE = "active"


def paid_engagement_is_active(rfp: models.RFP) -> bool:
    return (getattr(rfp, "paid_engagement_status", None) or "none").strip() == PAID_ACTIVE


def paid_delivery_pipeline_started(rfp: models.RFP) -> bool:
    """FS·납품 코드 생성이 한 번이라도 건드려진 경우(testing / post-payment)."""
    fs_s = (getattr(rfp, "fs_status", None) or "none").strip()
    dc_s = (getattr(rfp, "delivered_code_status", None) or "none").strip()
    return fs_s != "none" or dc_s != "none"


def user_can_access_fs_hub(user: _UserLike | None, rfp: models.RFP) -> bool:
    """
    FS/납품 조회·다운로드 허용.

    - 결제 활성이면 항상 (소유자/관리자는 rfp_for_owner_or_admin 이후 여기 도달).
    - 관리자는 결제 여부와 무관하게 조회(테스트용).
    - 미결제여도 관리자가 FS/코드 생성을 시작했다면 소유자도 조회 가능.
    """
    if not user:
        return False
    if paid_engagement_is_active(rfp):
        return True
    if getattr(user, "is_admin", False):
        return True
    return paid_delivery_pipeline_started(rfp)


def rfp_eligible_for_stripe_checkout(rfp: models.RFP) -> bool:
    if not ((rfp.proposal_text or "").strip()):
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
