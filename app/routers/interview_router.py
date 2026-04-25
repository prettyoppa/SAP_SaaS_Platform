import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db
from ..templates_config import templates
from ..agents.agent_tools import get_code_library_context
from ..rfp_reference_code import format_reference_code_for_llm

router = APIRouter()


def _interview_trust_panel(db: Session, rfp: models.RFP) -> dict:
    """코드 라이브러리 매칭 여부 등 인터뷰 신뢰 UI용."""
    modules = [x.strip() for x in (rfp.sap_modules or "").split(",") if x.strip()]
    dev_types = [x.strip() for x in (rfp.dev_types or "").split(",") if x.strip()]
    ctx_raw = get_code_library_context(db, modules, dev_types)
    out = {"library_matched": False, "library_line": ""}
    if ctx_raw:
        try:
            cj = json.loads(ctx_raw)
            qs = cj.get("questions") or []
            has_summary = bool((cj.get("analysis_summary") or "").strip())
            out["library_matched"] = len(qs) > 0 or has_summary
            out["library_line"] = cj.get("source", "") or (
                "코드 라이브러리 유사 프로그램 요약" if has_summary else ""
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


def _format_round_answers(all_q: list[str], answers: list[str]) -> str:
    parts = []
    for i, (q, a) in enumerate(zip(all_q, answers), 1):
        parts.append(f"Q{i}:\n{q}\n\nA{i}:\n{a}")
    return "\n\n".join(parts)


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


def _run_proposal_background(rfp_id: int, rfp_dict: dict, conv: list[dict]):
    """BackgroundTask: 에이전트 Crew를 실행하여 Proposal을 생성하고 DB에 저장합니다."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        try:
            rfp_dict = _rfp_to_dict(rfp)
            conv = _messages_to_list(rfp.messages)
            code_ctx = get_code_library_context(
                db,
                rfp_dict.get("sap_modules", []),
                rfp_dict.get("dev_types", []),
            )
            proposal = _fc().generate_proposal(rfp_dict, conv, code_library_context=code_ctx)
        except Exception as ex:
            proposal = f"# Proposal 생성 오류\n\n{ex}"
        rfp.proposal_text = proposal
        rfp.interview_status = "completed"
        db.commit()
    finally:
        db.close()


# ── 라우트 ────────────────────────────────────────────

@router.get("/rfp/{rfp_id}/interview", response_class=HTMLResponse)
def interview_page(rfp_id: int, request: Request,
                   background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)

    if rfp.status == "draft":
        return RedirectResponse(url=f"/rfp/{rfp_id}/edit", status_code=302)

    trust = _interview_trust_panel(db, rfp)

    # Proposal 생성 완료 → 바로 proposal 페이지
    if rfp.interview_status == "completed" and rfp.proposal_text:
        return RedirectResponse(url=f"/rfp/{rfp_id}/proposal", status_code=302)

    # Proposal 생성 중 → 로딩 페이지
    if rfp.interview_status == "generating_proposal":
        return templates.TemplateResponse(request, "proposal_generating.html", {
            "request": request, "user": user, "rfp": rfp,
        })

    answered = [m for m in rfp.messages if m.is_answered]
    unanswered = [m for m in rfp.messages if not m.is_answered]

    # 미답변 질문이 있으면 그 화면 표시
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
            "interview_draft_wip": (intra or {}).get("draft_wip", "") or "",
            "answer_suggestions": [],
        }
        if seq and intra is not None:
            ans = intra.get("answers_so_far", [])
            if not isinstance(ans, list):
                ans = []
            qi = len(ans)
            if qi < len(current_questions):
                ctx_extra["current_question"] = current_questions[qi]
            else:
                err_extra = "이 라운드 질문 상태를 읽을 수 없습니다. 임시저장이 있었다면 복구를 시도하거나, 대시보드에서 인터뷰를 다시 열어 주세요."
            ctx_extra["interview_step_index"] = min(qi + 1, 3)
            ctx_extra["prior_in_round"] = [
                {"q": current_questions[i], "a": ans[i]} for i in range(min(qi, len(current_questions)))
            ]
            ctx_extra["answer_suggestions"] = _cap_suggestions(
                (intra or {}).get("current_suggestions")
            )
        return templates.TemplateResponse(request, "interview.html", {
            "request": request, "user": user, "rfp": rfp,
            "answered_messages": _messages_to_list(answered),
            "current_message": current_msg,
            "current_questions": current_questions,
            "current_round": current_msg.round_number,
            "max_rounds": _fc().MAX_ROUNDS,
            "question_source": current_msg.source_label or "AI 에이전트 생성",
            "error": err_extra,
            "interview_trust": trust,
            **ctx_extra,
        })

    # 모든 라운드 완료 → Proposal 생성 시작
    rfp_dict = _rfp_to_dict(rfp)
    conv = _messages_to_list(rfp.messages)
    next_round = len(rfp.messages) + 1

    if next_round > _fc().MAX_ROUNDS or (answered and len(answered) >= _fc().MAX_ROUNDS):
        rfp.interview_status = "generating_proposal"
        db.commit()
        background_tasks.add_task(_run_proposal_background, rfp.id, rfp_dict, conv)
        return templates.TemplateResponse(request, "proposal_generating.html", {
            "request": request, "user": user, "rfp": rfp,
        })

    # 다음 라운드 질문 생성 (에이전트 호출)
    code_ctx = get_code_library_context(
        db,
        rfp_dict.get("sap_modules", []),
        rfp_dict.get("dev_types", []),
    )
    try:
        result = _fc().generate_sequential_start(
            rfp_data=rfp_dict,
            conversation=conv,
            round_num=next_round,
            code_library_context=code_ctx,
        )
    except RuntimeError as e:
        return templates.TemplateResponse(request, "interview.html", {
            "request": request, "user": user, "rfp": rfp,
            "answered_messages": _messages_to_list(rfp.messages),
            "current_message": None,
            "current_questions": [],
            "current_round": next_round,
            "max_rounds": _fc().MAX_ROUNDS,
            "error": str(e),
            "interview_trust": trust,
            "question_source": "",
            "interview_sequential": True,
            "interview_legacy_batch": False,
            "current_question": None,
            "prior_in_round": [],
            "interview_step_index": 1,
            "interview_draft_wip": "",
            "answer_suggestions": [],
        })

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
    return templates.TemplateResponse(request, "interview.html", {
        "request": request, "user": user, "rfp": rfp,
        "answered_messages": _messages_to_list(answered),
        "current_message": new_msg,
        "current_questions": cq,
        "current_round": next_round,
        "max_rounds": _fc().MAX_ROUNDS,
        "question_source": result.get("source", "AI 에이전트 생성"),
        "error": None,
        "interview_trust": trust,
        "interview_sequential": True,
        "interview_legacy_batch": False,
        "current_question": cq[0] if cq else None,
        "prior_in_round": [],
        "interview_step_index": 1,
        "interview_draft_wip": intra_r.get("draft_wip", "") or "",
        "answer_suggestions": intra_r.get("current_suggestions") or [],
    })


@router.post("/rfp/{rfp_id}/interview/reset")
def reset_interview(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)

    for msg in rfp.messages:
        db.delete(msg)
    rfp.interview_status = "pending"
    rfp.proposal_text = None
    rfp.status = "submitted"
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)


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
        return RedirectResponse(url="/dashboard", status_code=302)

    # 순차 인터뷰는 /interview/answer-step 사용
    if _is_sequential_v2(msg):
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    msg.answers_text = answers_text.strip()
    msg.is_answered = True
    db.commit()
    return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)


@router.post("/rfp/{rfp_id}/interview/answer-step")
def interview_answer_step(
    rfp_id: int,
    request: Request,
    message_id: int = Form(...),
    current_answer: str = Form(""),
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
        return RedirectResponse(url="/dashboard", status_code=302)

    msg = db.query(models.RFPMessage).filter(
        models.RFPMessage.id == message_id,
        models.RFPMessage.rfp_id == rfp_id,
    ).first()
    if not msg or not _is_sequential_v2(msg):
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    intra = _parse_intra(msg) or {"v": 2, "answers_so_far": [], "library_pool": []}
    try:
        all_q = json.loads(msg.questions_json)
    except Exception:
        all_q = []
    if not isinstance(all_q, list) or not all_q:
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    lib_pool = intra.get("library_pool", [])
    if not isinstance(lib_pool, list):
        lib_pool = []
    answers_so: list = intra.get("answers_so_far", [])
    if not isinstance(answers_so, list):
        answers_so = []

    if action == "save_exit":
        intra["draft_wip"] = (current_answer or "").strip()
        intra["v"] = 2
        intra["answers_so_far"] = answers_so
        intra["library_pool"] = lib_pool
        msg.intra_state_json = json.dumps(intra, ensure_ascii=False)
        from datetime import datetime as _dt
        msg.updated_at = _dt.utcnow()
        db.commit()
        return RedirectResponse(url="/dashboard", status_code=302)

    intra.pop("draft_wip", None)
    if len(answers_so) >= 3:
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)
    # 다음에 답할 질문은 all_q[len(answers_so)]
    if len(answers_so) > len(all_q):
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    ans = (current_answer or "").strip()
    if not _answer_valid(ans):
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview?ans=empty", status_code=302)

    answers_so = answers_so + [ans]
    rfp_dict = _rfp_to_dict(rfp)
    conv = _messages_to_list([m for m in rfp.messages if m.is_answered])
    code_ctx = get_code_library_context(
        db, rfp_dict.get("sap_modules", []), rfp_dict.get("dev_types", [])
    )
    in_round: list = list(zip([all_q[i] for i in range(len(answers_so))], answers_so))

    if len(answers_so) < 3:
        fol = _fc().generate_sequential_followup(
            rfp_data=rfp_dict,
            conversation=conv,
            round_num=msg.round_number,
            in_round_qa=in_round,
            code_library_context=code_ctx,
            library_pool=lib_pool,
        )
        nq = (fol.get("next_question") or "").strip()
        if not nq:
            return RedirectResponse(url=f"/rfp/{rfp_id}/interview?ans=gen", status_code=302)
        all_q = all_q + [nq]
        lib_pool = list(fol.get("library_pool") or [])
        if msg.source_label and "코드 라이브러리" in (msg.source_label or "") and fol.get("source"):
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
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    # 3번째 답 — 라운드 완료
    if len(answers_so) == 3 and len(all_q) >= 3:
        msg.answers_text = _format_round_answers(all_q[:3], answers_so)
        msg.is_answered = True
        msg.intra_state_json = None
        from datetime import datetime as _dt3
        msg.updated_at = _dt3.utcnow()
        db.commit()
    return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)


@router.get("/rfp/{rfp_id}/proposal/status")
def proposal_status(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """프론트엔드 폴링용 – Proposal 생성 상태를 JSON으로 반환합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return {"status": "unauthorized"}
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return {"status": "not_found"}
    return {"status": rfp.interview_status}


@router.get("/rfp/{rfp_id}/proposal", response_class=HTMLResponse)
def proposal_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)

    if rfp.interview_status == "generating_proposal":
        return templates.TemplateResponse(request, "proposal_generating.html", {
            "request": request, "user": user, "rfp": rfp,
        })

    if not rfp.proposal_text:
        return RedirectResponse(url=f"/rfp/{rfp_id}/interview", status_code=302)

    return templates.TemplateResponse(request, "proposal.html", {
        "request": request, "user": user, "rfp": rfp,
        "proposal_html": _markdown_to_html(rfp.proposal_text),
        "messages": _messages_to_list(rfp.messages),
    })


@router.post("/rfp/{rfp_id}/interview/edit-answer")
def edit_answer(
    rfp_id: int, request: Request,
    message_id: int = Form(...),
    answers_text: str = Form(...),
    db: Session = Depends(get_db),
):
    """기존 인터뷰 답변을 수정합니다 (Proposal 미재생성)."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    msg = db.query(models.RFPMessage).filter(
        models.RFPMessage.id == message_id,
        models.RFPMessage.rfp_id == rfp_id,
    ).first()
    if not msg:
        return RedirectResponse(url="/dashboard", status_code=302)

    from datetime import datetime as _dt
    msg.answers_text = answers_text.strip()
    msg.updated_at = _dt.utcnow()
    db.commit()
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
        return RedirectResponse(url="/dashboard", status_code=302)

    rfp_dict = _rfp_to_dict(rfp)
    conv = _messages_to_list(rfp.messages)
    rfp.interview_status = "generating_proposal"
    rfp.proposal_text = None
    db.commit()
    background_tasks.add_task(_run_proposal_background, rfp.id, rfp_dict, conv)
    return RedirectResponse(url=f"/rfp/{rfp_id}/proposal/generating", status_code=302)


@router.get("/rfp/{rfp_id}/proposal/generating", response_class=HTMLResponse)
def proposal_generating_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)
    if rfp.interview_status == "completed" and rfp.proposal_text:
        return RedirectResponse(url=f"/rfp/{rfp_id}/proposal", status_code=302)
    return templates.TemplateResponse(request, "proposal_generating.html", {
        "request": request, "user": user, "rfp": rfp,
    })


@router.get("/rfp/{rfp_id}/proposal/download")
def download_proposal(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp or not rfp.proposal_text:
        return RedirectResponse(url="/dashboard", status_code=302)

    # ASCII 파일명만 사용(한글 파일명은 Content-Disposition에서 500 유발 가능)
    body = rfp.proposal_text
    if isinstance(body, str):
        body = body.encode("utf-8")
    filename = f"proposal_rfp_{rfp_id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Markdown → HTML ───────────────────────────────────

def _markdown_to_html(md: str) -> str:
    import re
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
    return "\n".join(result)
