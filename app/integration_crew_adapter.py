"""연동 요청 → free_crew 인터뷰·제안용 dict (Non-ABAP 맥락)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from . import models
from .devtype_catalog import format_integration_impl_types_for_llm
from .rfp_reference_code import format_reference_code_for_llm

if TYPE_CHECKING:
    pass


def _member_safe_for_integration(db: Session, ir: models.IntegrationRequest) -> bool:
    if not ir or not ir.user_id:
        return True
    owner = db.query(models.User).filter(models.User.id == ir.user_id).first()
    return not (owner and owner.is_admin)


def integration_request_to_crew_rfp_dict(db: Session, ir: models.IntegrationRequest) -> dict:
    """SAP ABAP RFP가 아니라도 crew가 기대하는 키 형태로 맞춤 (workflow_origin=integration_native)."""
    impl_disp = format_integration_impl_types_for_llm(db, ir.impl_types or "")
    parts = [
        "## [SAP 연동·비 ABAP 개발] 요청 본문",
        "",
        f"**제목:** {ir.title or ''}",
        f"**구현 형태:** {impl_disp or '—'}",
        "",
        "### SAP 터치포인트",
        (ir.sap_touchpoints or "").strip() or "—",
        "",
        "### 실행 환경",
        (ir.environment_notes or "").strip() or "—",
        "",
        "### 상세 설명",
        (ir.description or "").strip() or "—",
    ]
    desc = "\n".join(parts)
    payload = getattr(ir, "reference_code_payload", None)
    return {
        "title": (ir.title or "").strip() or "연동 개발 요청",
        "program_id": None,
        "transaction_code": None,
        "sap_modules": [],
        "dev_types": [x.strip() for x in (ir.impl_types or "").split(",") if x.strip()],
        "description": desc,
        "reference_code_for_agents": format_reference_code_for_llm(payload),
        "workflow_origin": "integration_native",
    }
