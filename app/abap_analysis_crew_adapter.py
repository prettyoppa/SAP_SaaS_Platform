"""ABAP 분석·개선 요청 → free_crew 제안·FS용 dict."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models
from .rfp_reference_code import format_reference_code_for_llm


def _member_safe_for_abap_analysis(db: Session, row: models.AbapAnalysisRequest) -> bool:
    if not row or not row.user_id:
        return True
    owner = db.query(models.User).filter(models.User.id == row.user_id).first()
    return not (owner and owner.is_admin)


def abap_analysis_request_to_crew_rfp_dict(db: Session, row: models.AbapAnalysisRequest) -> dict:
    """RFP와 동일 키 형태로 맞춤 (workflow_origin=abap_analysis)."""
    desc = "\n".join(
        [
            "## [SAP ABAP 분석·개선] 요청 본문",
            "",
            "### 원 요구사항",
            (row.requirement_text or "").strip() or "—",
            "",
            "### 개선 제안 요청",
            (row.improvement_request_text or "").strip() or "—",
        ]
    )
    payload = getattr(row, "reference_code_payload", None)
    mods = [x.strip() for x in (row.sap_modules or "").split(",") if x.strip()]
    dts = [x.strip() for x in (row.dev_types or "").split(",") if x.strip()]
    return {
        "title": (row.title or "").strip() or f"ABAP 분석·개선 #{row.id}",
        "program_id": (getattr(row, "program_id", None) or "").strip() or None,
        "transaction_code": (getattr(row, "transaction_code", None) or "").strip() or None,
        "sap_modules": mods,
        "dev_types": dts,
        "description": desc,
        "reference_code_for_agents": format_reference_code_for_llm(payload),
        "workflow_origin": "abap_analysis",
    }
