import json
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db
from ..templates_config import templates
from ..agents.agent_tools import get_code_library_context

router = APIRouter()


def _fc():
    """CrewAI는 import 비용이 커서 홈/대시보드 등에서는 로드하지 않습니다."""
    from ..agents import free_crew

    return free_crew


# ── 헬퍼 ─────────────────────────────────────────────

def _rfp_to_dict(rfp: models.RFP) -> dict:
    return {
        "title": rfp.title,
        "sap_modules": rfp.sap_modules.split(",") if rfp.sap_modules else [],
        "dev_types": rfp.dev_types.split(",") if rfp.dev_types else [],
        "description": rfp.description or "",
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


def _run_proposal_background(rfp_id: int, rfp_dict: dict, conv: list[dict]):
    """BackgroundTask: 에이전트 Crew를 실행하여 Proposal을 생성하고 DB에 저장합니다."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        try:
            proposal = _fc().generate_proposal(rfp_dict, conv)
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
        return templates.TemplateResponse(request, "interview.html", {
            "request": request, "user": user, "rfp": rfp,
            "answered_messages": _messages_to_list(answered),
            "current_message": current_msg,
            "current_questions": current_questions,
            "current_round": current_msg.round_number,
            "max_rounds": _fc().MAX_ROUNDS,
            "question_source": current_msg.source_label or "AI 에이전트 생성",
            "error": None,
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
        result = _fc().generate_round_questions(
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
        })

    new_msg = models.RFPMessage(
        rfp_id=rfp.id,
        round_number=next_round,
        questions_json=json.dumps(result["questions"], ensure_ascii=False),
        source_label=result.get("source", "AI 에이전트 생성"),
        is_answered=False,
    )
    rfp.interview_status = "in_progress"
    rfp.status = "in_review"
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    return templates.TemplateResponse(request, "interview.html", {
        "request": request, "user": user, "rfp": rfp,
        "answered_messages": _messages_to_list(answered),
        "current_message": new_msg,
        "current_questions": result["questions"],
        "current_round": next_round,
        "max_rounds": _fc().MAX_ROUNDS,
        "question_source": result.get("source", "AI 에이전트 생성"),
        "error": None,
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

    msg.answers_text = answers_text.strip()
    msg.is_answered = True
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

    safe = "".join(c for c in rfp.title if c.isalnum() or c in " _-")[:40].strip()
    filename = f"Proposal_{safe or rfp_id}.md"
    return PlainTextResponse(
        content=rfp.proposal_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type="text/markdown; charset=utf-8",
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
