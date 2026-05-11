"""연동 개발 — 인터뷰·제안서 POST/GET (경로만 /integration 기준)."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from .. import auth, models
from ..code_asset_access import user_may_copy_download_request_assets
from ..request_hub_access import apply_integration_hub_read_access
from ..database import get_db
from ..integration_hub import integration_hub_url
from ..integration_interview_service import (
    _run_integration_proposal_background,
    serve_integration_interview_workspace,
)
from ..subscription_catalog import METRIC_DEV_PROPOSAL, METRIC_DEV_PROPOSAL_REGEN
from ..subscription_quota import try_consume_monthly, try_consume_per_request
from ..integration_crew_adapter import integration_request_to_crew_rfp_dict, _member_safe_for_integration
from ..templates_config import templates
from ..agents.agent_tools import get_code_library_context
from ..agent_playbook import PlaybookContext, STAGE_INTERVIEW, build_playbook_addon
from .interview_router import (
    _answer_block_for_export,
    _fc,
    _format_round_answers,
    _interview_has_substance,
    _is_sequential_v2,
    _messages_to_list,
    _parse_answer_payload_form,
    _parse_intra,
    _step_payload_valid,
)

router = APIRouter()


def _ir_msgs(ir: models.IntegrationRequest):
    return sorted(list(ir.interview_messages or []), key=lambda m: (m.round_number, m.id))


def _substance(ir: models.IntegrationRequest) -> bool:
    class _M:
        def __init__(self, x):
            self.is_answered = x.is_answered
            self.answers_text = x.answers_text
            self.intra_state_json = x.intra_state_json

    class _F:
        messages: list

    f = _F()
    f.messages = [_M(m) for m in _ir_msgs(ir)]
    return _interview_has_substance(f)  # type: ignore[arg-type]


@router.get("/integration/{req_id}/interview/summary", response_class=HTMLResponse)
def integration_interview_summary_redirect(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir or (ir.status or "").strip().lower() == "draft":
        return RedirectResponse(url="/integration", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "interview", view_summary=True), status_code=302)


@router.get("/integration/{req_id}/interview", response_class=HTMLResponse)
def integration_interview_standalone_page(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.interview_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    out = serve_integration_interview_workspace(request, db, user, ir, background_tasks)
    if out.kind == "redirect":
        return RedirectResponse(url=out.redirect_url or "/", status_code=302)
    if out.kind == "generating":
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)
    return templates.TemplateResponse(request, "interview.html", out.wizard_ctx or {})


@router.post("/integration/{req_id}/interview/request-proposal-now")
def integration_request_proposal_now(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.interview_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    if ir.interview_status == "generating_proposal":
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)
    if ir.interview_status == "completed" and (ir.proposal_text or "").strip():
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)
    if not _substance(ir):
        return RedirectResponse(url=f"{integration_hub_url(req_id, 'interview')}&err=proposal", status_code=302)
    ir.interview_status = "generating_proposal"
    db.commit()
    background_tasks.add_task(_run_integration_proposal_background, ir.id)
    return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)


@router.post("/integration/{req_id}/interview/reset")
def integration_reset_interview(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.interview_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    for msg in list(ir.interview_messages or []):
        db.delete(msg)
    ir.interview_status = "pending"
    ir.proposal_text = None
    if (ir.status or "").strip().lower() != "draft":
        ir.status = "submitted"
    db.commit()
    return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)


@router.post("/integration/{req_id}/interview/answer")
def integration_submit_answer_legacy(
    req_id: int,
    request: Request,
    message_id: int = Form(...),
    answers_text: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    msg = (
        db.query(models.IntegrationInterviewMessage)
        .filter(
            models.IntegrationInterviewMessage.id == message_id,
            models.IntegrationInterviewMessage.integration_request_id == req_id,
        )
        .first()
    )
    if not msg:
        return RedirectResponse(url="/integration", status_code=302)
    if _is_sequential_v2(msg):
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)
    msg.answers_text = answers_text.strip()
    msg.is_answered = True
    db.commit()
    return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)


@router.post("/integration/{req_id}/interview/answer-step")
def integration_interview_answer_step(
    req_id: int,
    request: Request,
    message_id: int = Form(...),
    current_answer: str = Form(""),
    answer_payload: str = Form(""),
    action: str = Form("next"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.interview_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    msg = (
        db.query(models.IntegrationInterviewMessage)
        .filter(
            models.IntegrationInterviewMessage.id == message_id,
            models.IntegrationInterviewMessage.integration_request_id == req_id,
        )
        .first()
    )
    if not msg or not _is_sequential_v2(msg):
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    intra = _parse_intra(msg) or {"v": 2, "answers_so_far": [], "library_pool": []}
    try:
        all_q = json.loads(msg.questions_json)
    except Exception:
        all_q = []
    if not isinstance(all_q, list) or not all_q:
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    lib_pool = intra.get("library_pool", [])
    if not isinstance(lib_pool, list):
        lib_pool = []
    answers_so: list = intra.get("answers_so_far", [])
    if not isinstance(answers_so, list):
        answers_so = []

    if action == "save_exit":
        o = _parse_answer_payload_form(answer_payload, current_answer)
        intra["draft_wip"] = json.dumps(o, ensure_ascii=False)
        intra["v"] = 2
        intra["answers_so_far"] = answers_so
        intra["library_pool"] = lib_pool
        msg.intra_state_json = json.dumps(intra, ensure_ascii=False)
        msg.updated_at = datetime.utcnow()
        db.commit()
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    intra.pop("draft_wip", None)
    max_per_round = _fc().MAX_QUESTIONS_PER_ROUND
    if len(answers_so) >= max_per_round:
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)
    if len(answers_so) > len(all_q):
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    o = _parse_answer_payload_form(answer_payload, current_answer)
    if not _step_payload_valid(o):
        return RedirectResponse(url=f"{integration_hub_url(req_id, 'interview')}&ans=empty", status_code=302)
    ans = json.dumps(o, ensure_ascii=False)
    answers_so = answers_so + [ans]
    rfp_dict = integration_request_to_crew_rfp_dict(db, ir)
    conv = _messages_to_list([m for m in _ir_msgs(ir) if m.is_answered])
    _ms_ans = _member_safe_for_integration(db, ir)
    code_ctx = get_code_library_context(
        db,
        rfp_dict.get("sap_modules", []),
        rfp_dict.get("dev_types", []),
        member_safe_output=_ms_ans,
    )
    in_round: list = list(
        zip(
            [all_q[i] for i in range(len(answers_so))],
            [_answer_block_for_export(answers_so[i]) for i in range(len(answers_so))],
        )
    )

    def _finalize_message_row():
        n = min(len(answers_so), len(all_q))
        msg.answers_text = _format_round_answers(all_q[:n], answers_so[:n])
        msg.is_answered = True
        msg.intra_state_json = None
        msg.updated_at = datetime.utcnow()
        db.commit()

    if len(answers_so) >= max_per_round:
        _finalize_message_row()
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    pb_f = build_playbook_addon(
        db,
        PlaybookContext(entity="integration", stage=STAGE_INTERVIEW, workflow_origin="integration_native"),
    )
    fol = _fc().generate_sequential_followup(
        rfp_data=rfp_dict,
        conversation=conv,
        round_num=msg.round_number,
        in_round_qa=in_round,
        code_library_context=code_ctx,
        library_pool=lib_pool,
        member_safe_output=_ms_ans,
        playbook_addon=pb_f,
    )
    if bool(fol.get("round_complete")):
        _finalize_message_row()
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    nq = (fol.get("next_question") or "").strip()
    if not nq:
        _finalize_message_row()
        return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)

    all_q = all_q + [nq]
    lib_pool = list(fol.get("library_pool") or [])
    if msg.source_label and fol.get("source"):
        if "코드 라이브러리" in (msg.source_label or "") or "내부 유사" in (msg.source_label or ""):
            msg.source_label = fol.get("source", msg.source_label)
    msg.questions_json = json.dumps(all_q, ensure_ascii=False)
    intra["answers_so_far"] = answers_so
    intra["library_pool"] = lib_pool
    su = fol.get("suggested_answers")
    if isinstance(su, list):
        intra["current_suggestions"] = [str(x).strip() for x in su if str(x).strip()][:5]
    else:
        intra["current_suggestions"] = []
    intra["v"] = 2
    msg.intra_state_json = json.dumps(intra, ensure_ascii=False)
    msg.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)


@router.post("/integration/{req_id}/interview/edit-answer")
def integration_edit_answer(
    req_id: int,
    request: Request,
    message_id: int = Form(...),
    answers_text: str = Form(...),
    return_to: str = Form("proposal"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    msg = (
        db.query(models.IntegrationInterviewMessage)
        .join(
            models.IntegrationRequest,
            models.IntegrationInterviewMessage.integration_request_id == models.IntegrationRequest.id,
        )
        .filter(
            models.IntegrationInterviewMessage.id == message_id,
            models.IntegrationInterviewMessage.integration_request_id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not msg:
        return RedirectResponse(url="/integration", status_code=302)
    msg.answers_text = answers_text.strip()
    msg.updated_at = datetime.utcnow()
    db.commit()
    rt = (return_to or "proposal").strip()
    if rt == "interview-summary":
        return RedirectResponse(url=f"/integration/{req_id}/interview/summary", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)


@router.post("/integration/{req_id}/proposal/regenerate")
def integration_regenerate_proposal(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.interview_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    err_r = try_consume_per_request(db, user, METRIC_DEV_PROPOSAL_REGEN, "integration", req_id, 1)
    if err_r == "disabled":
        return RedirectResponse(
            url=f"{integration_hub_url(req_id, 'proposal')}&quota_err=proposal_regen_disabled",
            status_code=302,
        )
    if err_r == "per_request_limit":
        return RedirectResponse(
            url=f"{integration_hub_url(req_id, 'proposal')}&quota_err=proposal_regen_limit",
            status_code=302,
        )
    ir.interview_status = "generating_proposal"
    ir.proposal_text = None
    db.commit()
    background_tasks.add_task(_run_integration_proposal_background, ir.id)
    return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)


@router.get("/integration/{req_id}/proposal/status")
def integration_proposal_status(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return {"status": "unauthorized"}
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return {"status": "not_found"}
    return {"status": ir.interview_status}


@router.get("/integration/{req_id}/proposal", response_class=HTMLResponse)
def integration_proposal_redirect(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)


@router.get("/integration/{req_id}/proposal/download")
def integration_proposal_download(req_id: int, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import Response

    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = apply_integration_hub_read_access(
        db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id),
        user,
    )
    ir = q.first()
    if not ir or (ir.interview_status or "") != "completed" or not (ir.proposal_text or "").strip():
        return RedirectResponse(url="/integration", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="integration",
        request_id=req_id,
        owner_user_id=int(ir.user_id),
    ):
        return RedirectResponse(url="/integration", status_code=302)
    body = (ir.proposal_text or "").encode("utf-8")
    fname = f"integration-proposal-{req_id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/integration/{req_id}/proposal/generating", response_class=HTMLResponse)
def integration_proposal_generating_redirect(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=302)
