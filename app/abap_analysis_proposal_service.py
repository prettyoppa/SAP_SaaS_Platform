"""분석·개선 요청 — 인터뷰 없이 제안서 생성(시드 대화 1라운드)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from . import models
from .abap_analysis_crew_adapter import abap_analysis_request_to_crew_rfp_dict, _member_safe_for_abap_analysis
from .agent_playbook import PlaybookContext, STAGE_PROPOSAL, build_playbook_addon
from .agent_display import wrap_unbracketed_agent_names
from .agents.agent_tools import get_code_library_context
from .routers.interview_router import _fc
from .workflow_rfp_bridge import build_workflow_seed_answer_abap


def abap_analysis_synthetic_conversation(row: models.AbapAnalysisRequest) -> list[dict]:
    """제안서 에이전트용: 분석·후속·개선 요청을 한 라운드 답변으로 압축."""
    fmsgs = sorted(
        list(row.followup_messages or []),
        key=lambda m: (getattr(m, "created_at", None) or datetime.utcnow(), getattr(m, "id", 0)),
    )
    seed = build_workflow_seed_answer_abap(
        requirement_text=row.requirement_text or "",
        analysis_json_raw=getattr(row, "analysis_json", None),
        followup_messages=fmsgs,
        improvement_text=(row.improvement_request_text or "").strip(),
    )
    q = "[ABAP 분석·개선] 제안서 작성용 통합 요약"
    return [
        {
            "id": 0,
            "round_number": 1,
            "questions": [q],
            "answers_text": seed,
            "is_answered": True,
        }
    ]


def _playbook_addon_abap_analysis(db: Session) -> str:
    return build_playbook_addon(
        db,
        PlaybookContext(entity="abap_analysis", stage=STAGE_PROPOSAL, workflow_origin="abap_analysis"),
    )


def run_abap_analysis_proposal_background(analysis_id: int) -> None:
    from .database import SessionLocal

    db = SessionLocal()
    try:
        row = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.followup_messages))
            .filter(models.AbapAnalysisRequest.id == analysis_id)
            .first()
        )
        if not row:
            return
        try:
            rfp_dict = abap_analysis_request_to_crew_rfp_dict(db, row)
            conv = abap_analysis_synthetic_conversation(row)
            ms = _member_safe_for_abap_analysis(db, row)
            code_ctx = get_code_library_context(
                db,
                rfp_dict.get("sap_modules", []),
                rfp_dict.get("dev_types", []),
                member_safe_output=ms,
            )
            pb = _playbook_addon_abap_analysis(db)
            proposal = _fc().generate_proposal(
                rfp_dict,
                conv,
                code_library_context=code_ctx,
                member_safe_output=ms,
                playbook_addon=pb,
            )
        except Exception as ex:
            proposal = f"# Proposal 생성 오류\n\n{ex}"
        row.proposal_text = wrap_unbracketed_agent_names(proposal)
        row.proposal_generated_at = datetime.utcnow()
        row.interview_status = "completed"
        db.commit()
    finally:
        db.close()
