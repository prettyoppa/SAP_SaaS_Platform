"""유료 개발 의뢰(FS·납품 코드) 공통 헬퍼."""

from __future__ import annotations

from typing import Any

from . import models

PAID_ACTIVE = "active"


def paid_engagement_is_active(rfp: models.RFP) -> bool:
    return (getattr(rfp, "paid_engagement_status", None) or "none").strip() == PAID_ACTIVE


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
