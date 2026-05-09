"""
SAP ABAP 분석 요청 — abap_codes와 별도 테이블(abap_analysis_requests).
로그인 회원: 본인 건만. 관리자: 전체.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, r2_storage, sap_fields
from ..abap_followup_chat import (
    MAX_USER_TURNS_PER_REQUEST,
    generate_followup_reply,
    validate_user_message,
)
from ..database import get_db
from ..menu_landing import (
    DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    abap_analysis_menu_aggregate,
    filtered_abap_analysis_menu_rows,
    menu_landing_preset_params,
    menu_landing_url,
    parse_slashed_date,
    standard_menu_bucket_meta,
    user_proposal_pending_offer_badges,
)
from ..attachment_context import build_attachment_llm_digest
from ..offer_inquiry_service import (
    inquiries_by_offer_id,
    public_request_url,
    send_consultant_offer_inquiry_reply,
    send_offer_inquiry_from_owner,
)
from ..request_hub_access import consultant_has_request_offer
from ..request_offer_visibility import visible_request_offers_for_viewer
from ..rfp_reference_code import (
    abap_source_only_from_reference_payload,
    normalize_reference_code_payload,
    reference_code_program_groups_for_tabs,
)
from ..templates_config import layout_template_from_embed_query, templates
from ..writing_guides_service import get_writing_guides_by_lang_bundle
from .interview_router import _markdown_to_html
from .rfp_router import (
    MAX_RFP_ATTACHMENTS,
    _build_attachment_entries_from_uploads,
    _remove_stored_file,
    duplicate_attachment_entries,
    _rfp_core_fields_incomplete_response,
    _rfp_missing_core_field_labels,
)
from ..rfp_hub import rfp_hub_url
from ..workflow_rfp_bridge import create_workflow_rfp_from_abap_analysis

router = APIRouter(prefix="/abap-analysis", tags=["abap_analysis"])

MIN_IMPROVEMENT_PROPOSAL_LEN = 20

MIN_REQUIREMENT_LEN = 20
MIN_ABAP_SOURCE_LEN = 50
MIN_TITLE_LEN = 2
TITLE_MAX_LEN = 512


def _split_csv_chips(s: Optional[str]) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _abap_form_dict(
    *,
    title: str = "",
    requirement_text: str = "",
    program_id: str = "",
    transaction_code: str = "",
    sap_modules: Optional[List[str]] = None,
    dev_types: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
) -> dict:
    n = notes if notes is not None else [""] * 5
    pad = list(n) + [""] * 5
    return {
        "title": title or "",
        "requirement_text": requirement_text or "",
        "program_id": program_id or "",
        "transaction_code": transaction_code or "",
        "sap_modules": list(sap_modules or []),
        "dev_types": list(dev_types or []),
        "notes": pad[:5],
    }


def _abap_form_dict_from_row(row: models.AbapAnalysisRequest) -> dict:
    notes = _notes_from_entries(_attachment_entries(row))[:5]
    return _abap_form_dict(
        title=row.title or "",
        requirement_text=row.requirement_text or "",
        program_id=getattr(row, "program_id", None) or "",
        transaction_code=getattr(row, "transaction_code", None) or "",
        sap_modules=_split_csv_chips(getattr(row, "sap_modules", None)),
        dev_types=_split_csv_chips(getattr(row, "dev_types", None)),
        notes=notes,
    )


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


def _query_abap_readable(db: Session, user: models.User):
    """GET 상세 Console·조회 화면: 관리자는 전체; 컨설턴트는 본인·오퍼 건만; 일반은 본인."""
    q = db.query(models.AbapAnalysisRequest)
    if getattr(user, "is_admin", False):
        return q
    if getattr(user, "is_consultant", False):
        ro = models.RequestOffer
        offer_ok = exists().where(
            ro.request_kind == "analysis",
            ro.request_id == models.AbapAnalysisRequest.id,
            ro.consultant_user_id == user.id,
        )
        return q.filter(or_(models.AbapAnalysisRequest.user_id == user.id, offer_ok))
    return q.filter(models.AbapAnalysisRequest.user_id == user.id)


def _query_abap_console_embed(db: Session, user: models.User):
    """요청 Console iframe(읽기 전용): 관리자·컨설턴트는 목록과 동일하게 전체 분석 요청 미리보기."""
    if getattr(user, "is_admin", False) or getattr(user, "is_consultant", False):
        return db.query(models.AbapAnalysisRequest)
    return _query_abap_readable(db, user)


def _query_for_user(db: Session, user: models.User):
    q = db.query(models.AbapAnalysisRequest)
    if not user.is_admin:
        q = q.filter(models.AbapAnalysisRequest.user_id == user.id)
    return q


def _get_abap_row_readable(db: Session, user: models.User, req_id: int) -> Optional[models.AbapAnalysisRequest]:
    return _query_abap_readable(db, user).filter(models.AbapAnalysisRequest.id == req_id).first()


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


def _analysis_offer_rows(db: Session, req_id: int) -> list[models.RequestOffer]:
    return (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == req_id,
        )
        .order_by(models.RequestOffer.created_at.desc())
        .all()
    )


def _offered_analysis_id_set(db: Session, ids: list[int], *, pending_only: bool = False) -> set[int]:
    if not ids:
        return set()
    q = db.query(models.RequestOffer.request_id).filter(
        models.RequestOffer.request_kind == "analysis",
        models.RequestOffer.request_id.in_(ids),
    )
    if pending_only:
        q = q.filter(models.RequestOffer.status == "offered")
    rows = q.distinct().all()
    return {int(r[0]) for r in rows if r and r[0] is not None}


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
    sap_modules: Optional[List[str]] = None,
    dev_types: Optional[List[str]] = None,
) -> dict:
    from ..agents.free_crew import analyze_code_for_library, augment_abap_analysis_with_requirement

    att = attachment_entries if attachment_entries else []
    digest = build_attachment_llm_digest(att, max_total_chars=12_000)

    title_snip = requirement_text.strip()[:200] or "ABAP 분석"
    structural = analyze_code_for_library(
        source_code=source_code,
        title=title_snip,
        modules=list(sap_modules or []),
        dev_types=list(dev_types or []),
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
    db: Session,
    *,
    error: Optional[str],
    form: dict,
    ref_code_initial: Optional[dict],
    edit_row: Optional[models.AbapAnalysisRequest] = None,
    attachment_entries: Optional[list[dict]] = None,
    status_code: int = 200,
    form_chat_err: Optional[str] = None,
):
    modules = (
        db.query(models.SAPModule)
        .filter(models.SAPModule.is_active == True)
        .order_by(models.SAPModule.sort_order)
        .all()
    )
    from ..devtype_catalog import active_abap_devtypes

    devtypes = active_abap_devtypes(db)
    writing_tip_setting = (
        db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    )
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    ai_inquiry = None
    if edit_row:
        row_w = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.followup_messages))
            .filter(models.AbapAnalysisRequest.id == edit_row.id)
            .first()
        )
        if row_w:
            follow_msgs = sorted(
                list(row_w.followup_messages or []),
                key=lambda m: (m.created_at or row_w.created_at),
            )
            turns = _pair_abap_followup_turns(follow_msgs)
            n_fu = sum(1 for m in follow_msgs if (m.role or "") == "user")
            eff = _effective_abap_source(row_w).strip()
            ai_inquiry = {
                "mode": "live",
                "float_id": "abap-followup-chat",
                "size_key": "abap-followup-chat-size",
                "post_url": f"/abap-analysis/{row_w.id}/chat",
                "return_to": "edit",
                "followup_turns": turns,
                "chat_error": form_chat_err,
                "chat_limit_reached": n_fu >= MAX_USER_TURNS_PER_REQUEST,
                "max_turns": MAX_USER_TURNS_PER_REQUEST,
                "header_i18n": "chat.abapHeaderTitle",
                "context_i18n": "chat.abapContextHelp",
                "form_ready": bool(eff),
            }
    else:
        ai_inquiry = {
            "mode": "teaser",
            "float_id": "abap-new-ai-teaser",
            "teaser_i18n": "chat.formAiTeaserAbap",
        }

    return templates.TemplateResponse(
        request,
        "abap_analysis_form.html",
        {
            "request": request,
            "user": user,
            "error": error,
            "form": form,
            "ref_code_initial": ref_code_initial,
            "edit_row": edit_row,
            "attachment_entries": attachment_entries or [],
            "modules": modules,
            "devtypes": devtypes,
            "writing_tip": writing_tip,
            "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
            "ai_inquiry": ai_inquiry,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def abap_analysis_list(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)

    raw_settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    intro_md = (raw_settings.get("service_analysis_intro_md_ko") or "").strip() or DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO
    service_analysis_intro_html = _markdown_to_html(intro_md)

    qp = request.query_params
    bucket_raw = (qp.get("bucket") or "").strip() or None
    if bucket_raw and bucket_raw not in VALID_URL_BUCKETS:
        bucket_raw = None
    selected_bucket = bucket_raw

    title_search = (qp.get("title") or "").strip() or None
    date_from_raw = (qp.get("date_from") or "").strip() or None
    date_to_raw = (qp.get("date_to") or "").strip() or None
    date_from_dt = parse_slashed_date(date_from_raw)
    date_to_dt = parse_slashed_date(date_to_raw)

    menu_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    menu_total_rows = 0
    menu_tile_links: dict[str, str] = {}
    filtered_rows: list[models.AbapAnalysisRequest] = []
    show_request_owner = False
    proposal_offer_notice_count = 0

    if user:
        # 메뉴 첫 화면은 권한자도 본인 요청만 표시
        admin_view = False
        cnt, _b = abap_analysis_menu_aggregate(db, admin=admin_view, user_id=user.id)
        menu_counts = cnt
        menu_total_rows = sum(menu_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft"))
        presets = menu_landing_preset_params(request.query_params)
        menu_tile_links = {
            k: menu_landing_url("/abap-analysis", presets, k) for k in TILE_ORDER_WITH_ALL
        }
        if selected_bucket:
            filtered_rows = filtered_abap_analysis_menu_rows(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            offered_ids = _offered_analysis_id_set(
                db, [int(x.id) for x in filtered_rows], pending_only=True
            )
            for row in filtered_rows:
                ho = int(row.id) in offered_ids
                setattr(row, "has_offer", ho)
                if selected_bucket == "proposal" and ho:
                    proposal_offer_notice_count += 1
                setattr(row, "pulse_offer_bg", selected_bucket == "proposal" and ho)

    bucket_meta = standard_menu_bucket_meta()
    proposal_offer_badges = (
        user_proposal_pending_offer_badges(db, user.id) if user else {"rfp": False, "analysis": False, "integration": False}
    )

    return templates.TemplateResponse(
        request,
        "abap_analysis_list.html",
        {
            "request": request,
            "user": user,
            "service_analysis_intro_html": service_analysis_intro_html,
            "bucket_meta": bucket_meta,
            "menu_landing_counts": menu_counts,
            "menu_total_rows": menu_total_rows,
            "menu_tile_links": menu_tile_links,
            "menu_tile_order": list(TILE_ORDER_WITH_ALL),
            "selected_menu_bucket": selected_bucket,
            "menu_show_list": bool(user and selected_bucket),
            "menu_search_title": title_search or "",
            "menu_date_from_raw": date_from_raw or "",
            "menu_date_to_raw": date_to_raw or "",
            "filtered_menu_rows": filtered_rows if user else [],
            "show_request_owner": show_request_owner,
            "menu_landing_form_action": "/abap-analysis",
            "proposal_offer_badges": proposal_offer_badges,
            "proposal_offer_notice_count": proposal_offer_notice_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def abap_analysis_new_form(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    return _form_template_response(
        request,
        user,
        db,
        error=None,
        form=_abap_form_dict(),
        ref_code_initial=None,
        edit_row=None,
        attachment_entries=[],
    )


@router.post("/new")
async def abap_analysis_create(
    request: Request,
    title: str = Form(""),
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
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
    title_raw = title or ""
    title_clean = (title_raw.strip())[:TITLE_MAX_LEN]
    req_raw = requirement_text or ""
    req_clean = req_raw.strip()
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    ref_initial = _ref_initial_from_raw(reference_code_json)
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_state() -> dict:
        return _abap_form_dict(
            title=title_raw,
            requirement_text=req_raw,
            program_id=program_id,
            transaction_code=transaction_code,
            sap_modules=sap_modules,
            dev_types=dev_types,
            notes=notes_in,
        )

    def _bad(err: str, ref_init=None):
        return _form_template_response(
            request,
            user,
            db,
            error=err,
            form=_form_state(),
            ref_code_initial=ref_init if ref_init is not None else ref_initial,
            edit_row=None,
            attachment_entries=[],
            status_code=400,
        )

    if len(sap_modules) > 3 or len(dev_types) > 3:
        return _bad("max_selection")

    min_desc = 0 if is_draft_save else MIN_REQUIREMENT_LEN
    miss = _rfp_missing_core_field_labels(
        title_raw,
        program_id,
        sap_modules,
        dev_types,
        req_clean,
        min_description_chars=min_desc,
    )
    if miss:
        return _rfp_core_fields_incomplete_response(request, miss)

    pid, perr = sap_fields.validate_program_id(program_id, required=True)
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return _bad(err_key)

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return _bad(err_key)

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return _bad("too_many_attachments")

    att_entries: list[dict] = []
    if n_uploads > 0:
        att_entries, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return _bad(err_a)

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return _bad("reference_code_too_large", ref_init=ref_initial)

    src = abap_source_only_from_reference_payload(norm_ref).strip() if norm_ref else ""

    if is_draft_save:
        row = models.AbapAnalysisRequest(
            user_id=user.id,
            title=title_clean,
            program_id=pid,
            transaction_code=tc,
            sap_modules=",".join(sap_modules) if sap_modules else "",
            dev_types=",".join(dev_types) if dev_types else "",
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

    if len(title_clean) < MIN_TITLE_LEN:
        return _bad("need_title")
    if not norm_ref:
        return _bad("need_reference_code")
    if len(src) < MIN_ABAP_SOURCE_LEN:
        return _bad("code_too_short")

    analysis = _run_analysis(
        req_clean,
        src,
        att_entries,
        sap_modules=sap_modules,
        dev_types=dev_types,
    )
    analyzed = not bool(analysis.get("error"))

    row = models.AbapAnalysisRequest(
        user_id=user.id,
        title=title_clean,
        program_id=pid,
        transaction_code=tc,
        sap_modules=",".join(sap_modules) if sap_modules else "",
        dev_types=",".join(dev_types) if dev_types else "",
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


@router.post("/{req_id}/duplicate-request")
def abap_analysis_duplicate_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """본인 분석 요청의 입력 필드·첨부·참고 코드만 복사한 새 임시저장 건을 만듭니다."""
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    att = duplicate_attachment_entries(_attachment_entries(row), user_id=user.id)
    title = (row.title or "").strip()
    if title and not title.endswith(" (복사)"):
        title = f"{title} (복사)"
    src = (row.source_code or "").strip()
    if not src and row.reference_code_payload:
        src = abap_source_only_from_reference_payload(row.reference_code_payload).strip()
    new_row = models.AbapAnalysisRequest(
        user_id=user.id,
        title=title or "요청 복사",
        program_id=getattr(row, "program_id", None),
        transaction_code=getattr(row, "transaction_code", None),
        sap_modules=getattr(row, "sap_modules", None),
        dev_types=getattr(row, "dev_types", None),
        requirement_text=row.requirement_text or "",
        reference_code_payload=row.reference_code_payload,
        source_code=src,
        is_draft=True,
        is_analyzed=False,
        analysis_json=None,
        workflow_rfp_id=None,
        improvement_request_text=None,
    )
    _set_attachments(new_row, att)
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return RedirectResponse(url=f"/abap-analysis/{new_row.id}/edit", status_code=302)


@router.get("/{req_id}/edit", response_class=HTMLResponse)
def abap_analysis_edit_form(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or not row.is_draft:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    chat_err = (request.query_params.get("chat_err") or "").strip() or None
    return _form_template_response(
        request,
        user,
        db,
        error=None,
        form=_abap_form_dict_from_row(row),
        ref_code_initial=_ref_initial_from_row(row),
        edit_row=row,
        attachment_entries=_attachment_entries(row),
        form_chat_err=chat_err,
    )


@router.post("/{req_id}/edit")
async def abap_analysis_edit_save(
    req_id: int,
    request: Request,
    title: str = Form(""),
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
    requirement_text: str = Form(""),
    reference_code_json: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    note_orig_0: str = Form(""),
    note_orig_1: str = Form(""),
    note_orig_2: str = Form(""),
    note_orig_3: str = Form(""),
    note_orig_4: str = Form(""),
    delete_0: str = Form(""),
    delete_1: str = Form(""),
    delete_2: str = Form(""),
    delete_3: str = Form(""),
    delete_4: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or not row.is_draft:
        return RedirectResponse(url="/abap-analysis", status_code=302)

    title_raw = title or ""
    title_clean = (title_raw.strip())[:TITLE_MAX_LEN]
    req_raw = requirement_text or ""
    req_clean = req_raw.strip()
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    notes_orig = [note_orig_0, note_orig_1, note_orig_2, note_orig_3, note_orig_4]
    del_flags = [bool(delete_0), bool(delete_1), bool(delete_2), bool(delete_3), bool(delete_4)]
    ref_initial = _ref_initial_from_raw(reference_code_json)
    is_draft_save = (save_action or "").strip().lower() == "draft"
    existing_att = _attachment_entries(row)

    def _form_state() -> dict:
        return _abap_form_dict(
            title=title_raw,
            requirement_text=req_raw,
            program_id=program_id,
            transaction_code=transaction_code,
            sap_modules=sap_modules,
            dev_types=dev_types,
            notes=notes_in,
        )

    def _bad(err: str, ref_init=None):
        return _form_template_response(
            request,
            user,
            db,
            error=err,
            form=_form_state(),
            ref_code_initial=ref_init if ref_init is not None else ref_initial,
            edit_row=row,
            attachment_entries=existing_att,
            status_code=400,
        )

    if len(sap_modules) > 3 or len(dev_types) > 3:
        return _bad("max_selection")

    min_desc = 0 if is_draft_save else MIN_REQUIREMENT_LEN
    miss = _rfp_missing_core_field_labels(
        title_raw,
        program_id,
        sap_modules,
        dev_types,
        req_clean,
        min_description_chars=min_desc,
    )
    if miss:
        return _rfp_core_fields_incomplete_response(request, miss)

    pid, perr = sap_fields.validate_program_id(program_id, required=True)
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return _bad(err_key)

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return _bad(err_key)

    kept: list[dict] = []
    for i, att in enumerate(existing_att):
        if i < len(del_flags) and del_flags[i]:
            _remove_stored_file(att.get("path"))
            continue
        note = (notes_orig[i] if i < len(notes_orig) else "") or ""
        kept.append({
            "path": att["path"],
            "filename": att.get("filename", ""),
            "note": note.strip(),
        })

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return _bad("too_many_attachments")

    new_parts: list[dict] = []
    if n_uploads > 0:
        new_parts, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return _bad(err_a)

    remaining = MAX_RFP_ATTACHMENTS - len(kept)
    if len(new_parts) > remaining:
        return _bad("too_many_attachments")

    merged_att = kept + new_parts

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return _bad("reference_code_too_large", ref_init=ref_initial)

    src = abap_source_only_from_reference_payload(norm_ref).strip() if norm_ref else ""

    if is_draft_save:
        row.title = title_clean
        row.program_id = pid
        row.transaction_code = tc
        row.sap_modules = ",".join(sap_modules) if sap_modules else ""
        row.dev_types = ",".join(dev_types) if dev_types else ""
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

    if len(title_clean) < MIN_TITLE_LEN:
        return _bad("need_title")
    if not norm_ref:
        return _bad("need_reference_code")
    if len(src) < MIN_ABAP_SOURCE_LEN:
        return _bad("code_too_short")

    analysis = _run_analysis(
        req_clean,
        src,
        merged_att,
        sap_modules=sap_modules,
        dev_types=dev_types,
    )
    analyzed = not bool(analysis.get("error"))
    row.title = title_clean
    row.program_id = pid
    row.transaction_code = tc
    row.sap_modules = ",".join(sap_modules) if sap_modules else ""
    row.dev_types = ",".join(dev_types) if dev_types else ""
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


def _prepare_abap_analysis_detail_ctx(
    *,
    req_id: int,
    request: Request,
    db: Session,
    user: models.User,
    readonly_console: bool,
) -> RedirectResponse | dict[str, Any]:
    base_q = _query_abap_console_embed(db, user) if readonly_console else _query_abap_readable(db, user)
    row = (
        base_q.options(
            joinedload(models.AbapAnalysisRequest.followup_messages),
            joinedload(models.AbapAnalysisRequest.workflow_rfp).joinedload(models.RFP.messages),
        )
        .filter(models.AbapAnalysisRequest.id == req_id)
        .first()
    )
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    analysis: dict = {}
    if row.analysis_json:
        try:
            analysis = json.loads(row.analysis_json)
        except Exception:
            analysis = {}
    owner = None
    if getattr(user, "is_admin", False) or (
        readonly_console and getattr(user, "is_consultant", False)
    ) or consultant_has_request_offer(
        db, consultant_user_id=user.id, request_kind="analysis", request_id=row.id
    ):
        owner = db.query(models.User).filter(models.User.id == row.user_id).first()

    eff_src = _effective_abap_source(row)
    program_groups = reference_code_program_groups_for_tabs(getattr(row, "reference_code_payload", None))
    if not program_groups and eff_src.strip():
        program_groups = [
            {
                "program_id": "",
                "transaction_code": "",
                "title": "",
                "sections": [{"tab_label": "소스", "code": eff_src}],
            }
        ]

    vis_offers = visible_request_offers_for_viewer(
        _analysis_offer_rows(db, row.id),
        viewer=user,
        owner_user_id=row.user_id,
        privileged_operator=bool(user.is_admin),
    )
    offer_panel_ctx = {
        "request_offers": vis_offers,
        "request_offer_inquiries_by_offer_id": inquiries_by_offer_id(db, [int(o.id) for o in vis_offers]),
        "request_offer_inquiry_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/inquiry",
        "request_offer_inquiry_reply_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/inquiry-reply",
        "request_offer_can_inquire": bool(not readonly_console and user.id == row.user_id),
        "offer_inquiry_request_detail_url": public_request_url(
            request, f"/abap-analysis/{row.id}#abap-phase-offers"
        ),
        "offer_inquiry_err": (request.query_params.get("offer_inquiry_err") or "").strip(),
        "offer_inquiry_ok": (request.query_params.get("offer_inquiry_ok") or "").strip() == "1",
        "offer_inquiry_reply_err": (request.query_params.get("offer_inquiry_reply_err") or "").strip(),
        "offer_inquiry_reply_ok": (request.query_params.get("offer_inquiry_reply_ok") or "").strip() == "1",
    }

    if readonly_console:
        return {
            "request": request,
            "user": user,
            "row": row,
            "analysis": analysis,
            "attachment_entries": _attachment_entries(row),
            "owner": owner,
            "source_program_groups": program_groups,
            **offer_panel_ctx,
            "request_offer_can_match": False,
            "request_offer_profile_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/profile",
            "request_offer_match_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/match",
        }

    followup_messages = sorted(
        list(row.followup_messages or []),
        key=lambda m: (m.created_at or row.created_at),
    )
    n_followup_user = sum(1 for m in followup_messages if (m.role or "") == "user")
    followup_turns = _pair_abap_followup_turns(followup_messages)
    chat_enabled = (not row.is_draft) and bool(eff_src.strip())
    chat_limit_reached = n_followup_user >= MAX_USER_TURNS_PER_REQUEST
    chat_error = (request.query_params.get("chat_err") or "").strip() or None
    wf_err = (request.query_params.get("wf_err") or "").strip() or None
    return {
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
        "wf_err": wf_err,
        "source_program_groups": program_groups,
        "max_followup_user_turns": MAX_USER_TURNS_PER_REQUEST,
        **offer_panel_ctx,
        "request_offer_can_match": bool(user and row and user.id == row.user_id),
        "request_offer_profile_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/profile",
        "request_offer_match_url_builder": lambda offer_id: f"/abap-analysis/{row.id}/offers/{int(offer_id)}/match",
    }


@router.get("/{req_id}/console-readonly", response_class=HTMLResponse)
def abap_analysis_detail_console_readonly(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    ctx = _prepare_abap_analysis_detail_ctx(
        req_id=req_id,
        request=request,
        db=db,
        user=user,
        readonly_console=True,
    )
    if isinstance(ctx, RedirectResponse):
        return ctx
    ctx["layout_template"] = layout_template_from_embed_query(request)
    return templates.TemplateResponse(request, "abap_analysis_detail_readonly.html", ctx)


@router.get("/{req_id}", response_class=HTMLResponse)
def abap_analysis_detail(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    ctx = _prepare_abap_analysis_detail_ctx(
        req_id=req_id,
        request=request,
        db=db,
        user=user,
        readonly_console=False,
    )
    if isinstance(ctx, RedirectResponse):
        return ctx
    return templates.TemplateResponse(request, "abap_analysis_detail.html", ctx)


@router.post("/{req_id}/improvement-proposal")
def abap_analysis_improvement_proposal_post(
    req_id: int,
    request: Request,
    improvement_request_text: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row_el = _query_for_user(db, user).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not row_el or row_el.is_draft or not row_el.is_analyzed:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    if getattr(row_el, "workflow_rfp_id", None):
        return RedirectResponse(url=f"/abap-analysis/{req_id}?wf_err=already", status_code=302)
    txt = (improvement_request_text or "").strip()
    if len(txt) < MIN_IMPROVEMENT_PROPOSAL_LEN:
        return RedirectResponse(url=f"/abap-analysis/{req_id}?wf_err=short", status_code=302)

    rfp = create_workflow_rfp_from_abap_analysis(
        db,
        row=row_el,
        improvement_text=txt,
        owner_user_id=user.id,
        followup_messages=None,
    )
    return RedirectResponse(url=rfp_hub_url(rfp.id, "request"), status_code=302)


@router.post("/{req_id}/chat")
def abap_analysis_chat_post(
    req_id: int,
    request: Request,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=303)
    chat_base = f"/abap-analysis/{req_id}/edit" if row.is_draft else f"/abap-analysis/{req_id}"
    eff_src = _effective_abap_source(row)
    if not eff_src.strip():
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote('코드가 없어 AI 문의를 시작할 수 없습니다.')}",
            status_code=303,
        )

    msg, verr = validate_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote(verr)}",
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
            url=f"{chat_base}?chat_err={quote('이 분석 건의 후속 질문은 상한에 도달했습니다.')}",
            status_code=303,
        )

    analysis: dict = {}
    if row.analysis_json:
        try:
            analysis = json.loads(row.analysis_json)
        except Exception:
            analysis = {}
    if row.is_draft:
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
    return RedirectResponse(url=f"{chat_base}#abap-followup-chat", status_code=303)


@router.post("/{req_id}/offers/{offer_id}/match")
def abap_analysis_offer_match(
    req_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
    if not row or row.user_id != user.id:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)
    if (offer.status or "") == "matched":
        offer.status = "offered"
        offer.matched_at = None
        db.add(offer)
        db.commit()
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)
    db.query(models.RequestOffer).filter(
        models.RequestOffer.request_kind == "analysis",
        models.RequestOffer.request_id == req_id,
    ).update({"status": "offered", "matched_at": None}, synchronize_session=False)
    offer.status = "matched"
    offer.matched_at = datetime.utcnow()
    db.add(offer)
    db.commit()
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)


@router.post("/{req_id}/offers/{offer_id}/inquiry")
def abap_analysis_offer_inquiry_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
    if not row or row.user_id != user.id:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)
    title = (row.title or "").strip() or f"분석 #{req_id}"
    detail = public_request_url(request, f"/abap-analysis/{req_id}#abap-phase-offers")
    err, _row = send_offer_inquiry_from_owner(
        db,
        author=user,
        offer=offer,
        consultant=offer.consultant,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = f"/abap-analysis/{req_id}"
    sep = "&" if "?" in base else "?"
    suffix = "#abap-phase-offers"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_err={quote(err)}{suffix}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_ok=1{suffix}", status_code=303)


@router.post("/{req_id}/offers/{offer_id}/inquiry-reply")
def abap_analysis_offer_inquiry_reply_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    if not getattr(user, "is_consultant", False):
        return RedirectResponse(url="/", status_code=302)
    row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)
    owner = db.query(models.User).filter(models.User.id == row.user_id).first()
    if not owner:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-offers", status_code=303)
    title = (row.title or "").strip() or f"분석 #{req_id}"
    detail = public_request_url(request, f"/abap-analysis/{req_id}#abap-phase-offers")
    err, _row = send_consultant_offer_inquiry_reply(
        db,
        consultant=user,
        offer=offer,
        owner=owner,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = f"/abap-analysis/{req_id}"
    sep = "&" if "?" in base else "?"
    suffix = "#abap-phase-offers"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_err={quote(err)}{suffix}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_ok=1{suffix}", status_code=303)


@router.get("/{req_id}/offers/{offer_id}/profile")
def abap_analysis_offer_profile_download(
    req_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
    if not row or row.user_id != user.id:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    path = (getattr(offer.consultant, "consultant_profile_file_path", None) or "").strip()
    fname = (getattr(offer.consultant, "consultant_profile_file_name", None) or "consultant_profile").strip() or "consultant_profile"
    if not path:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
        return RedirectResponse(url=r2_storage.presigned_get_url(ref, fname), status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    return FileResponse(ref, filename=fname)


@router.get("/{req_id}/attachment")
def abap_analysis_download_attachment(
    req_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
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
