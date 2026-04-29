"""
SAP ABAP 분석 요청 — abap_codes와 별도 테이블(abap_analysis_requests).
로그인 회원: 본인 건만. 관리자: 전체.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, r2_storage
from ..abap_followup_chat import (
    MAX_USER_TURNS_PER_REQUEST,
    generate_followup_reply,
    validate_user_message,
)
from ..database import get_db
from ..attachment_context import build_attachment_llm_digest
from ..rfp_reference_code import (
    abap_source_only_from_reference_payload,
    normalize_reference_code_payload,
    reference_code_sections_for_tabs,
)
from ..templates_config import templates
from .rfp_router import (
    MAX_RFP_ATTACHMENTS,
    _build_attachment_entries_from_uploads,
    _remove_stored_file,
)

router = APIRouter(prefix="/abap-analysis", tags=["abap_analysis"])

MIN_REQUIREMENT_LEN = 20
MIN_ABAP_SOURCE_LEN = 50


def _ref_initial_from_raw(reference_code_json: str) -> Optional[dict]:
    if not reference_code_json or not str(reference_code_json).strip():
        return None
    try:
        data = json.loads(reference_code_json)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _ref_initial_from_row(row: models.AbapAnalysisRequest) -> Optional[dict]:
    p = getattr(row, "reference_code_payload", None)
    if not p or not str(p).strip():
        return None
    try:
        data = json.loads(p)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _require_user(request: Request, db: Session) -> models.User:
    user = auth.get_current_user(request, db)
    if not user:
        nu = quote(request.url.path + ("?" + request.url.query if request.url.query else ""), safe="")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={nu}"},
        )
    return user


def _query_for_user(db: Session, user: models.User):
    q = db.query(models.AbapAnalysisRequest)
    if not user.is_admin:
        q = q.filter(models.AbapAnalysisRequest.user_id == user.id)
    return q


def _get_request_for_user(
    db: Session, user: models.User, req_id: int
) -> Optional[models.AbapAnalysisRequest]:
    return _query_for_user(db, user).filter(models.AbapAnalysisRequest.id == req_id).first()


def _attachment_entries(row: models.AbapAnalysisRequest) -> list[dict]:
    if not getattr(row, "attachments_json", None):
        return []
    try:
        data = json.loads(row.attachments_json)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("path")]
    except Exception:
        pass
    return []


def _set_attachments(row: models.AbapAnalysisRequest, entries: list[dict]) -> None:
    if not entries:
        row.attachments_json = None
        return
    row.attachments_json = json.dumps(entries, ensure_ascii=False)


def _effective_abap_source(row: models.AbapAnalysisRequest) -> str:
    """저장 시점에 슬롯 마커 없이 합쳐진 본문만 있을 수 있으므로, 참조 JSON이 있으면 항상 재계산해 사용."""
    p = getattr(row, "reference_code_payload", None)
    if p and str(p).strip():
        rec = abap_source_only_from_reference_payload(p).strip()
        if rec:
            return rec
    return (row.source_code or "").strip()


def _notes_from_entries(entries: list[dict]) -> list[str]:
    return [(e.get("note") or "")[:200] for e in entries] + [""] * 5


def _pair_abap_followup_turns(msgs: list) -> list[dict]:
    """user → assistant 순을 한 턴으로 묶어 상세 화면 접이식 UI에 사용."""
    out: list[dict] = []
    i = 0
    n = len(msgs)
    while i < n:
        m = msgs[i]
        role = (getattr(m, "role", None) or "").strip().lower()
        if role == "user":
            q = m
            a = None
            if i + 1 < n and (getattr(msgs[i + 1], "role", None) or "").strip().lower() == "assistant":
                a = msgs[i + 1]
                i += 2
            else:
                i += 1
            out.append({"question": q, "answer": a})
        elif role == "assistant":
            out.append({"question": None, "answer": m})
            i += 1
        else:
            i += 1
    return out


def _run_analysis(
    requirement_text: str,
    source_code: str,
    attachment_entries: Optional[list[dict]] = None,
) -> dict:
    from ..agents.free_crew import analyze_code_for_library, augment_abap_analysis_with_requirement

    att = attachment_entries if attachment_entries else []
    digest = build_attachment_llm_digest(att, max_total_chars=12_000)

    title_snip = requirement_text.strip()[:200] or "ABAP 분석"
    structural = analyze_code_for_library(
        source_code=source_code,
        title=title_snip,
        modules=[],
        dev_types=[],
        include_interview_questions=False,
        attachment_digest=digest,
    )
    out = dict(structural)
    if not structural.get("error"):
        aug = augment_abap_analysis_with_requirement(
            requirement_text,
            structural,
            source_code,
            attachment_digest=digest,
        )
        if aug.get("error"):
            out["requirement_analysis_error"] = aug["error"]
        else:
            out["requirement_analysis"] = {k: v for k, v in aug.items() if k != "error"}
    return out


def _form_template_response(
    request: Request,
    user: models.User,
    *,
    error: Optional[str],
    form_requirement: str,
    ref_code_initial: Optional[dict],
    edit_row: Optional[models.AbapAnalysisRequest] = None,
    attachment_entries: Optional[list[dict]] = None,
    notes_prefill: Optional[list[str]] = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "abap_analysis_form.html",
        {
            "request": request,
            "user": user,
            "error": error,
            "form_requirement": form_requirement,
            "ref_code_initial": ref_code_initial,
            "edit_row": edit_row,
            "attachment_entries": attachment_entries or [],
            "notes_prefill": notes_prefill,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def abap_analysis_list(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    rows = (
        _query_for_user(db, user)
        .options(joinedload(models.AbapAnalysisRequest.owner))
        .order_by(models.AbapAnalysisRequest.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "abap_analysis_list.html",
        {"request": request, "user": user, "rows": rows},
    )


@router.get("/new", response_class=HTMLResponse)
def abap_analysis_new_form(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    return _form_template_response(
        request,
        user,
        error=None,
        form_requirement="",
        ref_code_initial=None,
        notes_prefill=None,
    )


@router.post("/new")
async def abap_analysis_create(
    request: Request,
    requirement_text: str = Form(""),
    reference_code_json: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    req_raw = requirement_text or ""
    req_clean = req_raw.strip()
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    ref_initial = _ref_initial_from_raw(reference_code_json)
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _bad(err: str, ref_init=None):
        return _form_template_response(
            request,
            user,
            error=err,
            form_requirement=req_raw,
            ref_code_initial=ref_init if ref_init is not None else ref_initial,
            status_code=400,
        )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return _bad("reference_code_too_large", ref_init=ref_initial)

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return _bad("too_many_attachments")

    att_entries: list[dict] = []
    if n_uploads > 0:
        att_entries, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return _bad(err_a)
    src = abap_source_only_from_reference_payload(norm_ref).strip() if norm_ref else ""

    if is_draft_save:
        row = models.AbapAnalysisRequest(
            user_id=user.id,
            requirement_text=req_clean,
            reference_code_payload=norm_ref,
            source_code=src,
            analysis_json=None,
            is_analyzed=False,
            is_draft=True,
        )
        _set_attachments(row, att_entries)
        db.add(row)
        db.commit()
        db.refresh(row)
        return RedirectResponse(url=f"/abap-analysis/{row.id}/edit", status_code=302)

    if len(req_clean) < MIN_REQUIREMENT_LEN:
        return _bad("need_requirement")
    if not norm_ref:
        return _bad("need_reference_code")
    if len(src) < MIN_ABAP_SOURCE_LEN:
        return _bad("code_too_short")

    analysis = _run_analysis(req_clean, src, att_entries)
    analyzed = not bool(analysis.get("error"))

    row = models.AbapAnalysisRequest(
        user_id=user.id,
        requirement_text=req_clean,
        reference_code_payload=norm_ref,
        source_code=src,
        analysis_json=json.dumps(analysis, ensure_ascii=False),
        is_analyzed=analyzed,
        is_draft=False,
    )
    _set_attachments(row, att_entries)
    db.add(row)
    db.commit()
    db.refresh(row)
    return RedirectResponse(url=f"/abap-analysis/{row.id}", status_code=302)


@router.get("/{req_id}/edit", response_class=HTMLResponse)
def abap_analysis_edit_form(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or not row.is_draft:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    notes = _notes_from_entries(_attachment_entries(row))[:5]
    return _form_template_response(
        request,
        user,
        error=None,
        form_requirement=row.requirement_text or "",
        ref_code_initial=_ref_initial_from_row(row),
        edit_row=row,
        attachment_entries=_attachment_entries(row),
        notes_prefill=notes,
    )


@router.post("/{req_id}/edit")
async def abap_analysis_edit_save(
    req_id: int,
    request: Request,
    requirement_text: str = Form(""),
    reference_code_json: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or not row.is_draft:
        return RedirectResponse(url="/abap-analysis", status_code=302)

    req_raw = requirement_text or ""
    req_clean = req_raw.strip()
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    ref_initial = _ref_initial_from_raw(reference_code_json)
    is_draft_save = (save_action or "").strip().lower() == "draft"
    existing_att = _attachment_entries(row)

    def _bad(err: str, ref_init=None):
        return _form_template_response(
            request,
            user,
            error=err,
            form_requirement=req_raw,
            ref_code_initial=ref_init if ref_init is not None else ref_initial,
            edit_row=row,
            attachment_entries=existing_att,
            notes_prefill=notes_in,
            status_code=400,
        )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return _bad("reference_code_too_large", ref_init=ref_initial)

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return _bad("too_many_attachments")

    merged_att = list(existing_att)
    if n_uploads > 0:
        new_e, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return _bad(err_a)
        merged_att = merged_att + (new_e or [])
        if len(merged_att) > MAX_RFP_ATTACHMENTS:
            return _bad("too_many_attachments")

    src = abap_source_only_from_reference_payload(norm_ref).strip() if norm_ref else ""

    if is_draft_save:
        row.requirement_text = req_clean
        row.reference_code_payload = norm_ref
        row.source_code = src
        row.is_draft = True
        row.is_analyzed = False
        row.analysis_json = None
        _set_attachments(row, merged_att)
        db.add(row)
        db.commit()
        return RedirectResponse(url=f"/abap-analysis/{row.id}/edit", status_code=302)

    if len(req_clean) < MIN_REQUIREMENT_LEN:
        return _bad("need_requirement")
    if not norm_ref:
        return _bad("need_reference_code")
    if len(src) < MIN_ABAP_SOURCE_LEN:
        return _bad("code_too_short")

    analysis = _run_analysis(req_clean, src, att_entries)
    analyzed = not bool(analysis.get("error"))
    row.requirement_text = req_clean
    row.reference_code_payload = norm_ref
    row.source_code = src
    row.analysis_json = json.dumps(analysis, ensure_ascii=False)
    row.is_analyzed = analyzed
    row.is_draft = False
    _set_attachments(row, merged_att)
    db.add(row)
    db.commit()
    return RedirectResponse(url=f"/abap-analysis/{row.id}", status_code=302)


@router.get("/{req_id}", response_class=HTMLResponse)
def abap_analysis_detail(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    analysis = {}
    if row.analysis_json:
        try:
            analysis = json.loads(row.analysis_json)
        except Exception:
            analysis = {}
    owner = None
    if user.is_admin:
        owner = db.query(models.User).filter(models.User.id == row.user_id).first()

    followup_messages = (
        db.query(models.AbapAnalysisFollowupMessage)
        .filter(models.AbapAnalysisFollowupMessage.request_id == row.id)
        .order_by(models.AbapAnalysisFollowupMessage.created_at.asc())
        .all()
    )
    n_followup_user = sum(1 for m in followup_messages if (m.role or "") == "user")
    followup_turns = _pair_abap_followup_turns(followup_messages)
    eff_src = _effective_abap_source(row)
    chat_enabled = (not row.is_draft) and bool(eff_src.strip())
    chat_limit_reached = n_followup_user >= MAX_USER_TURNS_PER_REQUEST
    chat_error = (request.query_params.get("chat_err") or "").strip() or None
    src_secs = reference_code_sections_for_tabs(getattr(row, "reference_code_payload", None))
    if not src_secs:
        eff_only = _effective_abap_source(row)
        if eff_only.strip():
            src_secs = [
                {
                    "tab_label": "소스",
                    "code": eff_only,
                    "include_name": None,
                    "program_id": "",
                    "transaction_code": "",
                }
            ]

    return templates.TemplateResponse(
        request,
        "abap_analysis_detail.html",
        {
            "request": request,
            "user": user,
            "row": row,
            "analysis": analysis,
            "attachment_entries": _attachment_entries(row),
            "owner": owner,
            "followup_turns": followup_turns,
            "chat_enabled": chat_enabled,
            "chat_limit_reached": chat_limit_reached,
            "chat_error": chat_error,
            "source_sections": src_secs,
            "abap_source_line_count": len(eff_src.splitlines()) if eff_src else 0,
            "max_followup_user_turns": MAX_USER_TURNS_PER_REQUEST,
        },
    )


@router.post("/{req_id}/chat")
def abap_analysis_chat_post(
    req_id: int,
    request: Request,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or row.is_draft:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=303)
    eff_src = _effective_abap_source(row)
    if not eff_src.strip():
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?chat_err={quote('분석에 사용된 코드가 없어 대화를 시작할 수 없습니다.')}",
            status_code=303,
        )

    msg, verr = validate_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?chat_err={quote(verr)}",
            status_code=303,
        )

    n_user = (
        db.query(models.AbapAnalysisFollowupMessage)
        .filter(
            models.AbapAnalysisFollowupMessage.request_id == row.id,
            models.AbapAnalysisFollowupMessage.role == "user",
        )
        .count()
    )
    if n_user >= MAX_USER_TURNS_PER_REQUEST:
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?chat_err={quote('이 분석 건의 후속 질문은 상한에 도달했습니다.')}",
            status_code=303,
        )

    analysis: dict = {}
    if row.analysis_json:
        try:
            analysis = json.loads(row.analysis_json)
        except Exception:
            analysis = {}

    prior = (
        db.query(models.AbapAnalysisFollowupMessage)
        .filter(models.AbapAnalysisFollowupMessage.request_id == row.id)
        .order_by(models.AbapAnalysisFollowupMessage.created_at.asc())
        .all()
    )

    try:
        att_digest = build_attachment_llm_digest(_attachment_entries(row), max_total_chars=10_000)
        reply = generate_followup_reply(
            requirement_text=row.requirement_text or "",
            source_code=eff_src,
            analysis_obj=analysis,
            history_messages=prior,
            user_question=msg,
            attachment_digest=att_digest,
        )
    except Exception:
        reply = "응답을 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    db.add(
        models.AbapAnalysisFollowupMessage(
            request_id=row.id,
            role="user",
            content=msg,
        )
    )
    db.add(
        models.AbapAnalysisFollowupMessage(
            request_id=row.id,
            role="assistant",
            content=reply,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-followup-chat", status_code=303)


@router.get("/{req_id}/attachment")
def abap_analysis_download_attachment(
    req_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    entries = _attachment_entries(row)
    if idx < 0 or idx >= len(entries):
        return RedirectResponse(url="/abap-analysis", status_code=302)
    ent = entries[idx]
    path = ent.get("path")
    fname = ent.get("filename") or "attachment"
    if not path:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
        url = r2_storage.presigned_get_url(ref, fname)
        return RedirectResponse(url=url, status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    return FileResponse(ref, filename=fname)


@router.post("/{req_id}/reanalyze")
def abap_analysis_reanalyze(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if row.is_draft:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    eff_src = _effective_abap_source(row)
    analysis = _run_analysis(row.requirement_text or "", eff_src, _attachment_entries(row))
    analyzed = not bool(analysis.get("error"))
    row.source_code = eff_src
    row.analysis_json = json.dumps(analysis, ensure_ascii=False)
    row.is_analyzed = analyzed
    db.add(row)
    db.commit()
    return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)


@router.post("/{req_id}/delete")
def abap_analysis_delete(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    for ent in _attachment_entries(row):
        _remove_stored_file(ent.get("path"))
    db.delete(row)
    db.commit()
    return RedirectResponse(url="/abap-analysis", status_code=302)
