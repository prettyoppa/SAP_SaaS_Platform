import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session, joinedload
from .. import models, auth
from ..database import get_db
from ..templates_config import templates
from ..agents.agent_tools import get_code_library_context
from ..rfp_reference_code import format_reference_code_for_llm
from ..agent_display import wrap_unbracketed_agent_names
from ..code_asset_access import user_may_copy_download_request_assets
from ..rfp_phase_gates import rfp_for_owner_or_admin
from ..stripe_service import stripe_keys_configured
from ..paid_tier import paid_engagement_is_active, rfp_eligible_for_stripe_checkout
from ..rfp_hub import rfp_hub_url
from ..subscription_catalog import METRIC_DEV_PROPOSAL, METRIC_DEV_PROPOSAL_REGEN
from ..subscription_quota import try_consume_monthly, try_consume_per_request

router = APIRouter()


def _member_safe_for_rfp(db: Session, rfp: Optional[models.RFP]) -> bool:
    """일반 회원이 소유한 RFP이면 True — 에이전트 산출물에서 저장소 명칭 제거."""
    if not rfp or not rfp.user_id:
        return True
    owner = db.query(models.User).filter(models.User.id == rfp.user_id).first()
    return not (owner and owner.is_admin)


def _interview_trust_panel(db: Session, rfp: models.RFP) -> dict:
    """코드 라이브러리 매칭 여부 등 인터뷰 신뢰 UI용."""
    modules = [x.strip() for x in (rfp.sap_modules or "").split(",") if x.strip()]
    dev_types = [x.strip() for x in (rfp.dev_types or "").split(",") if x.strip()]
    ctx_raw = get_code_library_context(db, modules, dev_types, member_safe_output=False)
    out = {"library_matched": False, "library_line": ""}
    if ctx_raw:
        try:
            cj = json.loads(ctx_raw)
            qs = cj.get("questions") or []
            has_summary = bool((cj.get("analysis_summary") or "").strip())
            out["library_matched"] = len(qs) > 0 or has_summary
            out["library_line"] = cj.get("source", "") or (
                "유사 프로그램 분석 요약" if has_summary else ""
            )
        except Exception:
            pass
    return out


def _fc():
    """CrewAI는 import 비용이 커서 홈/대시보드 등에서는 로드하지 않습니다."""
    from ..agents import free_crew

    return free_crew


# ── 헬퍼 ─────────────────────────────────────────────

def _rfp_to_dict(rfp: models.RFP) -> dict:
    payload = getattr(rfp, "reference_code_payload", None)
    wo = (getattr(rfp, "workflow_origin", None) or "direct").strip()
    return {
        "title": rfp.title,
        "program_id": (getattr(rfp, "program_id", None) or "").strip() or None,
        "transaction_code": (getattr(rfp, "transaction_code", None) or "").strip() or None,
        "sap_modules": [x.strip() for x in rfp.sap_modules.split(",") if x.strip()]
        if rfp.sap_modules
        else [],
        "dev_types": [x.strip() for x in rfp.dev_types.split(",") if x.strip()]
        if rfp.dev_types
        else [],
        "description": rfp.description or "",
        "reference_code_for_agents": format_reference_code_for_llm(payload),
        "workflow_origin": wo or "direct",
    }


def _messages_to_list(messages) -> list[dict]:
    result = []
    for m in messages:
        try:
            questions = json.loads(m.questions_json)
        except Exception:
            questions = [m.questions_json]
        result.append({
            "id": m.id,
            "round_number": m.round_number,
            "questions": questions,
            "answers_text": m.answers_text or "",
            "is_answered": m.is_answered,
        })
    return result


def _conversation_list_for_llm(rfp: models.RFP) -> list[dict]:
    """답이 완료된 라운드 + 순차 v2 **진행 중** 라운드(일부 답)까지 Proposal·LLM용으로 합친다."""
    out: list[dict] = []
    for m in sorted(rfp.messages, key=lambda x: (x.round_number, x.id)):
        if m.is_answered:
            out.extend(_messages_to_list([m]))
            continue
        if not _is_sequential_v2(m):
            continue
        intra = _parse_intra(m) or {}
        ans = intra.get("answers_so_far", [])
        if not isinstance(ans, list) or not ans:
            continue
        try:
            all_q = json.loads(m.questions_json)
        except Exception:
            all_q = []
        if not isinstance(all_q, list) or not all_q:
            continue
        n = min(len(all_q), len(ans))
        if n < 1:
            continue
        atext = _format_round_answers(all_q[:n], ans[:n])
        out.append({
            "id": m.id,
            "round_number": m.round_number,
            "questions": all_q[:n],
            "answers_text": "[이 라운드: 일부 답만 제출·제안서용으로 포함]\n" + atext,
            "is_answered": False,
        })
    return out


def _interview_has_substance(rfp: models.RFP) -> bool:
    """완료된 답 또는 순차 v2에 저장된 답 1개 이상이 있으면 True."""
    for m in rfp.messages:
        if m.is_answered and (m.answers_text or "").strip():
            return True
        if not _is_sequential_v2(m):
            continue
        intra = _parse_intra(m) or {}
        a = intra.get("answers_so_far", [])
        if isinstance(a, list) and len(a) > 0:
            return True
    return False


def _parse_intra(msg: models.RFPMessage) -> Optional[dict]:
    raw = getattr(msg, "intra_state_json", None)
    if not raw:
        return None
    try:
        j = json.loads(raw)
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def _is_sequential_v2(msg: models.RFPMessage) -> bool:
    intra = _parse_intra(msg)
    return bool(intra and intra.get("v") == 2)


def _parse_stored_step_answer(s: str) -> Optional[dict]:
    """answers_so 한 항목: v1 JSON 또는 레거시(일반 문자열)."""
    t = (s or "").strip()
    if not t.startswith("{"):
        return None
    try:
        o = json.loads(t)
        if isinstance(o, dict) and o.get("v") == 1:
            return o
    except Exception:
        return None
    return None


def _format_parsed_step_answer(o: dict) -> str:
    """조회·Proposal·LLM용: 좋아요/싫어요/보충을 한 블록으로."""
    like = o.get("like") or []
    if not isinstance(like, list):
        like = []
    like = [str(x).strip() for x in like if str(x).strip()]
    dis = o.get("dislike") or []
    if not isinstance(dis, list):
        dis = []
    dis = [str(x).strip() for x in dis if str(x).strip()]
    free = (o.get("free") or "").strip()
    parts = []
    if like:
        parts.append("【선택(좋아요)】\n" + "\n".join(f"· {x}" for x in like))
    if dis:
        parts.append("【비선택(싫어요)】\n" + "\n".join(f"· {x}" for x in dis))
    if free:
        parts.append("【보충/추가】\n" + free)
    if parts:
        return "\n\n".join(parts)
    return free


def _answer_block_for_export(stored: str) -> str:
    """answers_so 한 항목 → Q/A 본문에 넣을 문자열."""
    p = _parse_stored_step_answer(stored)
    if p is not None:
        return _format_parsed_step_answer(p)
    return (stored or "").strip()


def _format_round_answers(all_q: list[str], answers: list[str]) -> str:
    parts = []
    for i, (q, a) in enumerate(zip(all_q, answers), 1):
        block = _answer_block_for_export(a)
        parts.append(f"Q{i}:\n{q}\n\nA{i}:\n{block}")
    return "\n\n".join(parts)


def _parse_answer_payload_form(
    answer_payload: str,
    current_answer: str,
) -> dict:
    """제출 폼 → v1 dict (like / dislike / free)."""
    raw = (answer_payload or "").strip()
    if raw.startswith("{"):
        try:
            o = json.loads(raw)
            if isinstance(o, dict):
                like = o.get("like") if isinstance(o.get("like"), list) else []
                dis = o.get("dislike") if isinstance(o.get("dislike"), list) else []
                free_val = o.get("free", "")
                free = (
                    (str(free_val).strip() if free_val is not None else "")
                    if isinstance(free_val, (str, int, float))
                    else ""
                )
                return {
                    "v": 1,
                    "like": [str(x).strip() for x in like if str(x).strip()],
                    "dislike": [str(x).strip() for x in dis if str(x).strip()],
                    "free": free,
                }
        except Exception:
            pass
    fr = (current_answer or "").strip()
    return {"v": 1, "like": [], "dislike": [], "free": fr}


def _step_payload_valid(o: dict) -> bool:
    return _answer_valid(_format_parsed_step_answer(o))


def _draft_wip_free_text(draft: str) -> str:
    """draft_wip가 v1 JSON이면 보충 란만, 아니면 전체(레거시)."""
    t = (draft or "").strip()
    if t.startswith("{"):
        try:
            o = json.loads(t)
            if isinstance(o, dict) and o.get("v") == 1:
                return (o.get("free") or "").strip() if isinstance(o.get("free"), str) else ""
        except Exception:
            return draft or ""
    return t


def _draft_wip_as_dict(draft: str) -> dict:
    """UI·스크립트 복원용 v1 dict."""
    t = (draft or "").strip()
    if t.startswith("{"):
        try:
            o = json.loads(t)
            if isinstance(o, dict) and o.get("v") == 1:
                o.setdefault("like", [])
                o.setdefault("dislike", [])
                o.setdefault("free", "")
                return o
        except Exception:
            pass
    if t:
        return {"v": 1, "like": [], "dislike": [], "free": t}
    return {"v": 1, "like": [], "dislike": [], "free": ""}


def _answer_valid(s: str) -> bool:
    t = (s or "").strip()
    if len(t) < 2:
        return False
    return True


def _cap_suggestions(xs) -> list:
    if not xs or not isinstance(xs, list):
        return []
    out = []
    for x in xs:
        t = str(x).strip()
        if t:
            out.append(t)
        if len(out) >= 5:
            break
    return out


def _run_proposal_background(rfp_id: int):
    """BackgroundTask: 에이전트 Crew를 실행하여 Proposal을 생성하고 DB에 저장합니다."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        try:
            rfp_dict = _rfp_to_dict(rfp)
            conv = _conversation_list_for_llm(rfp)
            ms = _member_safe_for_rfp(db, rfp)
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
        rfp.proposal_text = proposal
        rfp.interview_status = "completed"
        db.commit()
    finally:
        db.close()


@dataclass
class InterviewWorkspaceOutcome:
    kind: Literal["redirect", "generating", "wizard"]
    redirect_url: str | None = None
    wizard_ctx: dict[str, Any] | None = None


def serve_interview_workspace(
    request: Request,
    db: Session,
    user,
    rfp: models.RFP,
    background_tasks: BackgroundTasks,
) -> InterviewWorkspaceOutcome:
    """GET /rfp/:id/interview 와 동일한 분기·부작용(라운드 생성 등). 통합 허브에서 phase=interview 일 때만 호출."""
    rid = rfp.id
    if rfp.status == "draft":
        return InterviewWorkspaceOutcome(kind="redirect", redirect_url=f"/rfp/{rid}/edit")

    trust = _interview_trust_panel(db, rfp) if user.is_admin else None
    can_request_proposal = _interview_has_substance(rfp) and (rfp.interview_status or "") == "in_progress"

    if rfp.interview_status == "completed" and rfp.proposal_text:
        return InterviewWorkspaceOutcome(
            kind="redirect",
            redirect_url=rfp_hub_url(rid, "proposal"),
        )

    if rfp.interview_status == "generating_proposal":
        return InterviewWorkspaceOutcome(kind="generating")

    answered = [m for m in rfp.messages if m.is_answered]
    unanswered = [m for m in rfp.messages if not m.is_answered]

    if unanswered:
        current_msg = unanswered[0]
        current_questions = json.loads(current_msg.questions_json)
        intra = _parse_intra(current_msg)
        seq = _is_sequential_v2(current_msg)
        legacy_batch = (not seq) and len(current_questions) == 3
        err_extra = None
        ctx_extra = {
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
            ctx_extra["interview_draft_wip"] = _draft_wip_free_text(
                (intra or {}).get("draft_wip", "") or ""
            )
            ctx_extra["interview_draft_payload"] = _draft_wip_as_dict(
                (intra or {}).get("draft_wip", "") or ""
            )
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
                {
                    "q": current_questions[i],
                    "a": _answer_block_for_export(ans[i]),
                }
                for i in range(min(qi, len(current_questions)))
            ]
            ctx_extra["answer_suggestions"] = _cap_suggestions(
                (intra or {}).get("current_suggestions")
            )
        wizard_ctx = {
            "request": request,
            "user": user,
            "rfp": rfp,
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
        return InterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)

    rfp_dict = _rfp_to_dict(rfp)
    conv = _messages_to_list([m for m in rfp.messages if m.is_answered])
    next_round = len(rfp.messages) + 1

    if next_round > _fc().MAX_ROUNDS or (answered and len(answered) >= _fc().MAX_ROUNDS):
        err_p = try_consume_monthly(db, user, METRIC_DEV_PROPOSAL, 1)
        if err_p == "disabled":
            return InterviewWorkspaceOutcome(
                kind="redirect",
                redirect_url=f"{rfp_hub_url(rid, 'interview')}&quota_err=dev_proposal_disabled",
            )
        if err_p == "monthly_limit":
            return InterviewWorkspaceOutcome(
                kind="redirect",
                redirect_url=f"{rfp_hub_url(rid, 'interview')}&quota_err=dev_proposal_limit",
            )
        rfp.interview_status = "generating_proposal"
        db.commit()
        background_tasks.add_task(_run_proposal_background, rfp.id)
        return InterviewWorkspaceOutcome(kind="generating")

    _ms = _member_safe_for_rfp(db, rfp)
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
            "rfp": rfp,
            "answered_messages": _messages_to_list(rfp.messages),
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
        return InterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)

    intra_new = {
        "v": 2,
        "answers_so_far": [],
        "library_pool": list(result.get("library_pool") or []),
        "current_suggestions": _cap_suggestions(result.get("suggested_answers")),
    }
    new_msg = models.RFPMessage(
        rfp_id=rfp.id,
        round_number=next_round,
        questions_json=json.dumps(result["questions"], ensure_ascii=False),
        intra_state_json=json.dumps(intra_new, ensure_ascii=False),
        source_label=result.get("source", "AI 에이전트 생성"),
        is_answered=False,
    )
    rfp.interview_status = "in_progress"
    rfp.status = "in_review"
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    cq = result["questions"]
    intra_r = _parse_intra(new_msg) or {}
    wizard_ctx = {
        "request": request,
        "user": user,
        "rfp": rfp,
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
    return InterviewWorkspaceOutcome(kind="wizard", wizard_ctx=wizard_ctx)


# ── 라우트 ────────────────────────────────────────────

@router.get("/rfp/{rfp_id}/interview/summary", response_class=HTMLResponse)
def interview_summary_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """통합 허브 인터뷰 구역(view=summary)으로 이동."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    if rfp.status == "draft":
        return RedirectResponse(url=f"/rfp/{rfp_id}/edit", status_code=302)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "interview", view_summary=True), status_code=302)


@router.get("/rfp/{rfp_id}/interview", response_class=HTMLResponse)
def interview_page(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = (
        db.query(models.RFP)
        .options(joinedload(models.RFP.messages))
        .filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id)
        .first()
    )
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    out = serve_interview_workspace(request, db, user, rfp, background_tasks)
    if out.kind == "redirect":
        return RedirectResponse(url=out.redirect_url or "/", status_code=302)
    if out.kind == "generating":
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)
    return templates.TemplateResponse(request, "interview.html", out.wizard_ctx or {})


@router.post("/rfp/{rfp_id}/interview/request-proposal-now")
def request_proposal_now(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """인터뷰를 끝까지 가지 않고, 지금까지의 답(진행 중 라운드·일부 답 포함)으로 제안서 생성."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    if rfp.interview_status == "generating_proposal":
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)
    if rfp.interview_status == "completed" and rfp.proposal_text:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)
    if not _interview_has_substance(rfp):
        return RedirectResponse(url=f"{rfp_hub_url(rfp_id, 'interview')}&err=proposal", status_code=302)
    err_p = try_consume_monthly(db, user, METRIC_DEV_PROPOSAL, 1)
    if err_p == "disabled":
        return RedirectResponse(
            url=f"{rfp_hub_url(rfp_id, 'interview')}&quota_err=dev_proposal_disabled",
            status_code=302,
        )
    if err_p == "monthly_limit":
        return RedirectResponse(
            url=f"{rfp_hub_url(rfp_id, 'interview')}&quota_err=dev_proposal_limit",
            status_code=302,
        )
    rfp.interview_status = "generating_proposal"
    db.commit()
    background_tasks.add_task(_run_proposal_background, rfp.id)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)


@router.post("/rfp/{rfp_id}/interview/reset")
def reset_interview(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    for msg in rfp.messages:
        db.delete(msg)
    rfp.interview_status = "pending"
    rfp.proposal_text = None
    rfp.status = "submitted"
    db.commit()
    return RedirectResponse(url="/", status_code=302)


@router.post("/rfp/{rfp_id}/interview/answer")
def submit_answer(
    rfp_id: int, request: Request,
    message_id: int = Form(...),
    answers_text: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    msg = db.query(models.RFPMessage).filter(
        models.RFPMessage.id == message_id,
        models.RFPMessage.rfp_id == rfp_id,
    ).first()
    if not msg:
        return RedirectResponse(url="/", status_code=302)

    # 순차 인터뷰는 /interview/answer-step 사용
    if _is_sequential_v2(msg):
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    msg.answers_text = answers_text.strip()
    msg.is_answered = True
    db.commit()
    return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)


@router.post("/rfp/{rfp_id}/interview/answer-step")
def interview_answer_step(
    rfp_id: int,
    request: Request,
    message_id: int = Form(...),
    current_answer: str = Form(""),
    answer_payload: str = Form(""),
    action: str = Form("next"),
    db: Session = Depends(get_db),
):
    """순차 인터뷰: 한 질문 답변 → 서버에서 다음 질문 생성 후 돌아옵니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    msg = db.query(models.RFPMessage).filter(
        models.RFPMessage.id == message_id,
        models.RFPMessage.rfp_id == rfp_id,
    ).first()
    if not msg or not _is_sequential_v2(msg):
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    intra = _parse_intra(msg) or {"v": 2, "answers_so_far": [], "library_pool": []}
    try:
        all_q = json.loads(msg.questions_json)
    except Exception:
        all_q = []
    if not isinstance(all_q, list) or not all_q:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

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
        from datetime import datetime as _dt
        msg.updated_at = _dt.utcnow()
        db.commit()
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    intra.pop("draft_wip", None)
    max_per_round = _fc().MAX_QUESTIONS_PER_ROUND
    if len(answers_so) >= max_per_round:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)
    # 다음에 답할 질문은 all_q[len(answers_so)]
    if len(answers_so) > len(all_q):
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    o = _parse_answer_payload_form(answer_payload, current_answer)
    if not _step_payload_valid(o):
        return RedirectResponse(url=f"{rfp_hub_url(rfp_id, 'interview')}&ans=empty", status_code=302)
    ans = json.dumps(o, ensure_ascii=False)

    answers_so = answers_so + [ans]
    rfp_dict = _rfp_to_dict(rfp)
    conv = _messages_to_list([m for m in rfp.messages if m.is_answered])
    _ms_ans = _member_safe_for_rfp(db, rfp)
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
        from datetime import datetime as _dt3

        msg.updated_at = _dt3.utcnow()
        db.commit()

    if len(answers_so) >= max_per_round:
        _finalize_message_row()
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    fol = _fc().generate_sequential_followup(
        rfp_data=rfp_dict,
        conversation=conv,
        round_num=msg.round_number,
        in_round_qa=in_round,
        code_library_context=code_ctx,
        library_pool=lib_pool,
        member_safe_output=_ms_ans,
    )
    if bool(fol.get("round_complete")):
        _finalize_message_row()
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    nq = (fol.get("next_question") or "").strip()
    if not nq:
        _finalize_message_row()
        return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)

    all_q = all_q + [nq]
    lib_pool = list(fol.get("library_pool") or [])
    if msg.source_label and fol.get("source"):
        if (
            "코드 라이브러리" in (msg.source_label or "")
            or "내부 유사" in (msg.source_label or "")
        ):
            msg.source_label = fol.get("source", msg.source_label)
    msg.questions_json = json.dumps(all_q, ensure_ascii=False)
    intra["answers_so_far"] = answers_so
    intra["library_pool"] = lib_pool
    su = fol.get("suggested_answers")
    if isinstance(su, list):
        intra["current_suggestions"] = [
            str(x).strip() for x in su if str(x).strip()
        ][:5]
    else:
        intra["current_suggestions"] = []
    intra["v"] = 2
    msg.intra_state_json = json.dumps(intra, ensure_ascii=False)
    from datetime import datetime as _dt2

    msg.updated_at = _dt2.utcnow()
    db.commit()
    return RedirectResponse(url=rfp_hub_url(rfp_id, "interview"), status_code=302)


@router.get("/rfp/{rfp_id}/proposal/status")
def proposal_status(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """프론트엔드 폴링용 – Proposal 생성 상태를 JSON으로 반환합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return {"status": "unauthorized"}
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return {"status": "not_found"}
    return {"status": rfp.interview_status}


@router.get("/rfp/{rfp_id}/proposal", response_class=HTMLResponse)
def proposal_page(
    rfp_id: int,
    request: Request,
    checkout: str | None = None,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=True)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    from urllib.parse import urlencode

    q = {"phase": "proposal"}
    if (checkout or "").strip():
        q["checkout"] = (checkout or "").strip()
    return RedirectResponse(url=f"/rfp/{rfp_id}?{urlencode(q)}", status_code=302)


@router.post("/rfp/{rfp_id}/interview/edit-answer")
def edit_answer(
    rfp_id: int,
    request: Request,
    message_id: int = Form(...),
    answers_text: str = Form(...),
    return_to: str = Form("proposal"),
    db: Session = Depends(get_db),
):
    """기존 인터뷰 답변을 수정합니다 (Proposal 미재생성)."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    msg = (
        db.query(models.RFPMessage)
        .join(models.RFP, models.RFPMessage.rfp_id == models.RFP.id)
        .filter(
            models.RFPMessage.id == message_id,
            models.RFPMessage.rfp_id == rfp_id,
            models.RFP.user_id == user.id,
        )
        .first()
    )
    if not msg:
        return RedirectResponse(url="/", status_code=302)

    from datetime import datetime as _dt

    msg.answers_text = answers_text.strip()
    msg.updated_at = _dt.utcnow()
    db.commit()
    rt = (return_to or "proposal").strip()
    if rt == "interview-summary":
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview/summary", status_code=302)
    return RedirectResponse(url=f"/rfp/{rfp_id}/proposal", status_code=302)


@router.post("/rfp/{rfp_id}/proposal/regenerate")
def regenerate_proposal(
    rfp_id: int, request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """인터뷰 답변 수정 후 Proposal을 재생성합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    err_r = try_consume_per_request(db, user, METRIC_DEV_PROPOSAL_REGEN, "rfp", rfp_id, 1)
    if err_r == "disabled":
        return RedirectResponse(
            url=f"{rfp_hub_url(rfp_id, 'proposal')}&quota_err=proposal_regen_disabled",
            status_code=302,
        )
    if err_r == "per_request_limit":
        return RedirectResponse(
            url=f"{rfp_hub_url(rfp_id, 'proposal')}&quota_err=proposal_regen_limit",
            status_code=302,
        )
    rfp.interview_status = "generating_proposal"
    rfp.proposal_text = None
    db.commit()
    background_tasks.add_task(_run_proposal_background, rfp.id)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)


@router.get("/rfp/{rfp_id}/proposal/generating", response_class=HTMLResponse)
def proposal_generating_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)


@router.get("/rfp/{rfp_id}/proposal/download")
def download_proposal(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not rfp.proposal_text:
        return RedirectResponse(url="/", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="rfp",
        request_id=rfp_id,
        owner_user_id=int(rfp.user_id),
    ):
        return RedirectResponse(url="/", status_code=302)

    # ASCII 파일명만 사용(한글 파일명은 Content-Disposition에서 500 유발 가능)
    body = wrap_unbracketed_agent_names(rfp.proposal_text or "").encode("utf-8")
    filename = f"proposal_rfp_{rfp_id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Markdown → HTML ───────────────────────────────────

def _is_md_table_row(s: str) -> bool:
    t = s.strip()
    if "|" not in t or t.count("|") < 2:
        return False
    return t.startswith("|")


def _is_md_table_separator(s: str) -> bool:
    t = s.strip()
    if "|" not in t or "-" not in t:
        return False
    for ch in t:
        if ch not in "|-:+ \t|":
            return False
    return True


def _md_table_cells(line: str) -> list[str]:
    parts = [p.strip() for p in line.strip().split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _md_cell_inline_html(raw: str) -> str:
    from markupsafe import escape
    t = escape(str(raw))
    if "**" not in t:
        return t
    parts = t.split("**")
    out: list[str] = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(p)
        else:
            out.append(f"<strong>{p}</strong>")
    return "".join(out)


def _gfm_table_block_to_html(rows: list[str]) -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        cells = _md_table_cells(rows[0])
        if not any(c.strip() for c in cells):
            return ""
        tds = "".join(f"<td>{_md_cell_inline_html(c)}</td>" for c in cells)
        return (
            '<div class="proposal-table-wrap my-3">'
            '<table class="table table-bordered table-sm proposal-md-table align-middle">'
            f"<tbody><tr>{tds}</tr></tbody></table></div>"
        )
    if len(rows) >= 2 and _is_md_table_separator(rows[1]):
        head = _md_table_cells(rows[0])
        data_lines = rows[2:]
    else:
        head = _md_table_cells(rows[0])
        data_lines = rows[1:]

    ncols = max(
        len(head),
        max((len(_md_table_cells(x)) for x in data_lines), default=0),
    )
    ths = "".join(
        f'<th scope="col">{_md_cell_inline_html(head[i] if i < len(head) else "")}</th>'
        for i in range(ncols)
    )
    trs: list[str] = []
    for line in data_lines:
        b = _md_table_cells(line)
        tds = "".join(
            f"<td>{_md_cell_inline_html(b[i] if i < len(b) else '')}</td>" for i in range(ncols)
        )
        trs.append(f"<tr>{tds}</tr>")
    return (
        '<div class="proposal-table-wrap my-3">'
        '<table class="table table-bordered table-sm proposal-md-table align-middle">'
        f'<thead class="table-light"><tr>{ths}</tr></thead>'
        f"<tbody>{''.join(trs)}</tbody></table></div>"
    )


def _extract_md_tables_to_placeholders(md: str) -> tuple[str, list[str]]:
    """GFM 스타일 | 표| 를 잡아 HTML로 변환한 뒤 자리 표시자로 치환(이후 본문 처리)."""
    lines = md.split("\n")
    out_lines: list[str] = []
    tables: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_md_table_row(lines[i]):
            out_lines.append(lines[i])
            i += 1
            continue
        j, block = i, []
        while j < n:
            s = lines[j]
            if s.strip() == "":
                if j + 1 < n and _is_md_table_row(lines[j + 1]):
                    j += 1
                    continue
                break
            if _is_md_table_row(s):
                block.append(s)
                j += 1
            else:
                break
        if block:
            tables.append(_gfm_table_block_to_html(block))
            out_lines.append(f"__MDTABLE{len(tables) - 1}__")
            out_lines.append("")
        i = j
    return "\n".join(out_lines), tables


def _markdown_to_html(md: str) -> str:
    md = wrap_unbracketed_agent_names(md or "")
    md, table_parts = _extract_md_tables_to_placeholders(md)
    html = md
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^---+$", r"<hr>", html, flags=re.MULTILINE)

    lines = html.split("\n")
    result, in_list, list_type = [], False, None
    for line in lines:
        s = line.strip()
        m_tbl = re.match(r"^__MDTABLE(\d+)__$", s)
        if m_tbl:
            if in_list:
                result.append(f"</{list_type}>")
                in_list, list_type = False, None
            idx = int(m_tbl.group(1))
            if 0 <= idx < len(table_parts):
                result.append(table_parts[idx])
            continue
        if s.startswith("- "):
            if not in_list or list_type != "ul":
                if in_list:
                    result.append(f"</{list_type}>")
                result.append("<ul>")
                in_list, list_type = True, "ul"
            result.append(f"<li>{s[2:]}</li>")
        elif re.match(r"^\d+\.", s):
            if not in_list or list_type != "ol":
                if in_list:
                    result.append(f"</{list_type}>")
                result.append("<ol>")
                in_list, list_type = True, "ol"
            item_text = re.sub(r"^\d+\.\s*", "", s)
            result.append(f"<li>{item_text}</li>")
        else:
            if in_list:
                result.append(f"</{list_type}>")
                in_list, list_type = False, None
            result.append(f"<p>{line}</p>" if s and not s.startswith("<") else line)

    if in_list:
        result.append(f"</{list_type}>")
    return wrap_unbracketed_agent_names("\n".join(result))
