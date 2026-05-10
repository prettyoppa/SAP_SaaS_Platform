"""연동 개발 — AI 인터뷰·제안서 (RFP 인터뷰와 동일 분기, IntegrationInterviewMessage 사용)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import BackgroundTasks, Request
from sqlalchemy.orm import Session, joinedload

from . import models
from .agents.agent_tools import get_code_library_context
from .integration_crew_adapter import integration_request_to_crew_rfp_dict, _member_safe_for_integration
from .integration_hub import integration_hub_url
from .subscription_catalog import METRIC_DEV_PROPOSAL
from .subscription_quota import try_consume_monthly
from .routers.interview_router import (
    _answer_block_for_export,
    _cap_suggestions,
    _conversation_list_for_llm,
    _draft_wip_as_dict,
    _draft_wip_free_text,
    _fc,
    _format_round_answers,
    _interview_has_substance,
    _is_sequential_v2,
    _messages_to_list,
    _parse_intra,
)


def _ordered_interview_messages(ir: models.IntegrationRequest) -> list:
    msgs = list(ir.interview_messages or [])
    return sorted(msgs, key=lambda m: (m.round_number, m.id))


def _integration_conversation_for_crew(ir: models.IntegrationRequest) -> list[dict]:
    """RFP와 동일한 conversation 구조 — Integration 메시지를 임시 RFP에 얹어 재사용."""
    class _Msg:
        def __init__(self, m):
            self.id = m.id
            self.round_number = m.round_number
            self.questions_json = m.questions_json
            self.answers_text = m.answers_text
            self.is_answered = m.is_answered
            self.intra_state_json = m.intra_state_json

    class _FakeRfp:
        messages: list

    fake = _FakeRfp()
    fake.messages = [_Msg(m) for m in _ordered_interview_messages(ir)]
    return _conversation_list_for_llm(fake)  # type: ignore[arg-type]


def _integration_interview_has_substance(ir: models.IntegrationRequest) -> bool:
    class _Msg:
        def __init__(self, m):
            self.is_answered = m.is_answered
            self.answers_text = m.answers_text
            self.intra_state_json = m.intra_state_json

    class _FakeRfp:
        messages: list

    fake = _FakeRfp()
    fake.messages = [_Msg(m) for m in _ordered_interview_messages(ir)]
    return _interview_has_substance(fake)  # type: ignore[arg-type]


@dataclass
class IntegrationInterviewWorkspaceOutcome:
    kind: Literal["redirect", "generating", "wizard"]
    redirect_url: str | None = None
    wizard_ctx: dict[str, Any] | None = None


def _run_integration_proposal_background(integration_id: int):
    """BackgroundTask: IntegrationRequest에 Proposal 저장."""
    from .database import SessionLocal

    db = SessionLocal()
    try:
        ir = (
            db.query(models.IntegrationRequest)
            .options(joinedload(models.IntegrationRequest.interview_messages))
            .filter(models.IntegrationRequest.id == integration_id)
            .first()
        )
        if not ir:
            return
        try:
            rfp_dict = integration_request_to_crew_rfp_dict(db, ir)
            conv = _integration_conversation_for_crew(ir)
            ms = _member_safe_for_integration(db, ir)
            code_ctx = get_code_library_context(
                db,
                rfp_dict.get("sap_modules", []),
                rfp_dict.get("dev_types", []),
                member_safe_output=ms,
            )
            proposal = _fc().generate_proposal(
                rfp_dict,
                conv,
                code_library_context=code_ctx,
                member_safe_output=ms,
            )
        except Exception as ex:
            proposal = f"# Proposal 생성 오류\n\n{ex}"
        ir.proposal_text = proposal
        ir.interview_status = "completed"
        db.commit()
    finally:
        db.close()


def serve_integration_interview_workspace(
    request: Request,
    db: Session,
    user,
    ir: models.IntegrationRequest,
    background_tasks: BackgroundTasks,
) -> IntegrationInterviewWorkspaceOutcome:
    iid = ir.id
    st = (ir.status or "").strip().lower()
    if st == "draft":
        return IntegrationInterviewWorkspaceOutcome(
            kind="redirect", redirect_url=f"/integration/{iid}/edit"
        )

    trust = None
    can_request_proposal = _integration_interview_has_substance(ir) and (ir.interview_status or "") == "in_progress"

    if ir.interview_status == "completed" and (ir.proposal_text or "").strip():
        return IntegrationInterviewWorkspaceOutcome(
            kind="redirect",
            redirect_url=integration_hub_url(iid, "proposal"),
        )

    if ir.interview_status == "generating_proposal":
        return IntegrationInterviewWorkspaceOutcome(kind="generating")

    msgs = _ordered_interview_messages(ir)
    answered = [m for m in msgs if m.is_answered]
    unanswered = [m for m in msgs if not m.is_answered]

    if unanswered:
        current_msg = unanswered[0]
        current_questions = json.loads(current_msg.questions_json)
        intra = _parse_intra(current_msg)
        seq = _is_sequential_v2(current_msg)
        legacy_batch = (not seq) and len(current_questions) == 3
        err_extra = None
        ctx_extra: dict[str, Any] = {
            "interview_sequential": seq,
            "interview_legacy_batch": legacy_batch,
            "current_question": None,
            "prior_in_round": [],
            "interview_step_index": 1,
            "interview_max_questions": _fc().MAX_QUESTIONS_PER_ROUND,
            "interview_draft_wip": "",
            "interview_draft_payload": {"v": 1, "like": [], "dislike": [], "free": ""},
            "answer_suggestions": [],
        }
        if seq and intra is not None:
            ctx_extra["interview_draft_wip"] = _draft_wip_free_text((intra or {}).get("draft_wip", "") or "")
            ctx_extra["interview_draft_payload"] = _draft_wip_as_dict((intra or {}).get("draft_wip", "") or "")
            ans = intra.get("answers_so_far", [])
            if not isinstance(ans, list):
                ans = []
            qi = len(ans)
            if qi < len(current_questions):
                ctx_extra["current_question"] = current_questions[qi]
            else:
                err_extra = "이 라운드 질문 상태를 읽을 수 없습니다. 임시저장이 있었다면 복구를 시도하거나, 대시보드에서 인터뷰를 다시 열어 주세요."
            ctx_extra["interview_step_index"] = qi + 1
            ctx_extra["prior_in_round"] = [
                {"q": current_questions[i], "a": _answer_block_for_export(ans[i])}
                for i in range(min(qi, len(current_questions)))
            ]
            ctx_extra["answer_suggestions"] = _cap_suggestions((intra or {}).get("current_suggestions"))
        wizard_ctx = {
            "request": request,
            "user": user,
            "rfp": ir,
            "iv_submit_base": f"/integration/{iid}",
            "answered_messages": _messages_to_list(answered),
            "current_message": current_msg,
            "current_questions": current_questions,
            "current_round": current_msg.round_number,
            "max_rounds": _fc().MAX_ROUNDS,
            "question_source": current_msg.source_label or "AI 에이전트 생성",
            "error": err_extra,
            "interview_trust": trust,
            "can_request_proposal": can_request_proposal,
            **ctx_extra,
        }
        return IntegrationInterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)

    rfp_dict = integration_request_to_crew_rfp_dict(db, ir)
    conv = _messages_to_list([m for m in msgs if m.is_answered])
    next_round = len(msgs) + 1

    if next_round > _fc().MAX_ROUNDS or (answered and len(answered) >= _fc().MAX_ROUNDS):
        err_p = try_consume_monthly(db, user, METRIC_DEV_PROPOSAL, 1)
        if err_p == "disabled":
            return IntegrationInterviewWorkspaceOutcome(
                kind="redirect",
                redirect_url=f"{integration_hub_url(iid, 'interview')}&quota_err=dev_proposal_disabled",
            )
        if err_p == "monthly_limit":
            return IntegrationInterviewWorkspaceOutcome(
                kind="redirect",
                redirect_url=f"{integration_hub_url(iid, 'interview')}&quota_err=dev_proposal_limit",
            )
        ir.interview_status = "generating_proposal"
        db.commit()
        background_tasks.add_task(_run_integration_proposal_background, ir.id)
        return IntegrationInterviewWorkspaceOutcome(kind="generating")

    _ms = _member_safe_for_integration(db, ir)
    code_ctx = get_code_library_context(
        db,
        rfp_dict.get("sap_modules", []),
        rfp_dict.get("dev_types", []),
        member_safe_output=_ms,
    )
    try:
        result = _fc().generate_sequential_start(
            rfp_data=rfp_dict,
            conversation=conv,
            round_num=next_round,
            code_library_context=code_ctx,
            member_safe_output=_ms,
        )
    except RuntimeError as e:
        wizard_ctx = {
            "request": request,
            "user": user,
            "rfp": ir,
            "iv_submit_base": f"/integration/{ir.id}",
            "answered_messages": _messages_to_list(msgs),
            "current_message": None,
            "current_questions": [],
            "current_round": next_round,
            "max_rounds": _fc().MAX_ROUNDS,
            "error": str(e),
            "interview_trust": trust,
            "can_request_proposal": can_request_proposal,
            "question_source": "",
            "interview_sequential": True,
            "interview_legacy_batch": False,
            "current_question": None,
            "prior_in_round": [],
            "interview_step_index": 1,
            "interview_max_questions": _fc().MAX_QUESTIONS_PER_ROUND,
            "interview_draft_wip": "",
            "interview_draft_payload": {"v": 1, "like": [], "dislike": [], "free": ""},
            "answer_suggestions": [],
        }
        return IntegrationInterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)

    intra_new = {
        "v": 2,
        "answers_so_far": [],
        "library_pool": list(result.get("library_pool") or []),
        "current_suggestions": _cap_suggestions(result.get("suggested_answers")),
    }
    new_msg = models.IntegrationInterviewMessage(
        integration_request_id=ir.id,
        round_number=next_round,
        questions_json=json.dumps(result["questions"], ensure_ascii=False),
        intra_state_json=json.dumps(intra_new, ensure_ascii=False),
        source_label=result.get("source", "AI 에이전트 생성"),
        is_answered=False,
    )
    ir.interview_status = "in_progress"
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    cq = result["questions"]
    intra_r = _parse_intra(new_msg) or {}
    wizard_ctx = {
        "request": request,
        "user": user,
        "rfp": ir,
        "iv_submit_base": f"/integration/{iid}",
        "answered_messages": _messages_to_list(answered),
        "current_message": new_msg,
        "current_questions": cq,
        "current_round": next_round,
        "max_rounds": _fc().MAX_ROUNDS,
        "question_source": result.get("source", "AI 에이전트 생성"),
        "error": None,
        "interview_trust": trust,
        "can_request_proposal": can_request_proposal,
        "interview_sequential": True,
        "interview_legacy_batch": False,
        "current_question": cq[0] if cq else None,
        "prior_in_round": [],
        "interview_step_index": 1,
        "interview_max_questions": _fc().MAX_QUESTIONS_PER_ROUND,
        "interview_draft_wip": _draft_wip_free_text(intra_r.get("draft_wip", "") or ""),
        "interview_draft_payload": _draft_wip_as_dict(intra_r.get("draft_wip", "") or ""),
        "answer_suggestions": intra_r.get("current_suggestions") or [],
    }
    return IntegrationInterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)
