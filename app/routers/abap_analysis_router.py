"""
SAP ABAP 분석 요청 — abap_codes와 별도 테이블(abap_analysis_requests).
로그인 회원: 본인 건만. 관리자: 전체.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, r2_storage, sap_fields
from ..abap_followup_chat import (
    generate_followup_reply,
    validate_user_message,
)
from ..subscription_catalog import (
    METRIC_DEV_PROPOSAL,
    METRIC_DEV_PROPOSAL_REGEN,
    METRIC_DEV_REQUEST,
    METRIC_REQUEST_DUPLICATE,
)
from ..subscription_quota import (
    ai_inquiry_limit_reached,
    ai_inquiry_snapshot,
    consume_monthly,
    get_ai_inquiry_used,
    monthly_quota_exceeded,
    record_ai_inquiry_user_turn,
    try_consume_monthly,
    try_consume_per_request,
)
from ..database import get_db
from ..followup_messages_util import followup_created_at_sort_key
from ..request_hub_access import (
    abap_analysis_consultant_read_scope,
    consultant_is_matched_on_request,
    consultant_menu_matched_scope,
)
from ..menu_landing import (
    DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    abap_analysis_menu_aggregate,
    abap_analysis_menu_bucket,
    filtered_abap_analysis_menu_rows,
    menu_landing_preset_params,
    menu_landing_url,
    parse_slashed_date,
    standard_menu_bucket_meta,
    user_proposal_pending_offer_badges,
)
from ..attachment_context import build_attachment_llm_digest
from ..requirement_body import (
    apply_body as _apply_requirement_body_shared,
    body_plain as _requirement_body_plain,
    display_ctx as _requirement_display_ctx,
    has_body_context as requirement_has_body_context,
    inline_image_response,
    resolve_inline_entry,
    screenshot_entries as _screenshot_entries_from_row,
)
from ..requirement_rich_text import (
    html_to_plain_text,
    is_html_format,
    legacy_gallery_entries,
    sanitize_html,
)
from ..requirement_screenshots import (
    build_requirement_screenshots_llm_digest,
    duplicate_entries as duplicate_requirement_screenshots,
    entries_from_json as requirement_screenshot_entries_from_json,
    entries_to_json as requirement_screenshot_entries_to_json,
    remove_stored_entries as remove_requirement_screenshots,
)
from ..abap_analysis_proposal_service import run_abap_analysis_proposal_background
from ..agent_display import wrap_unbracketed_agent_names
from ..code_asset_access import user_may_copy_download_request_assets
from ..delivered_code_package import (
    delivered_package_has_body,
    parse_delivered_code_payload,
    rfp_delivered_body_ready,
)
from ..offer_inquiry_service import (
    inquiries_by_offer_id,
    notify_consultant_request_matched,
    public_request_url,
    send_consultant_offer_inquiry_reply,
    send_offer_inquiry_from_owner,
)
from ..request_offer_visibility import visible_request_offers_for_viewer
from ..rfp_download_names import (
    content_disposition_attachment,
    delivered_abap_download_basename,
    delivered_code_zip_basename,
)
from ..rfp_reference_code import (
    MAX_REFERENCE_CODE_BYTES,
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

router = APIRouter(prefix="/abap-analysis", tags=["abap_analysis"])


def _analysis_offer_rows(db: Session, analysis_id: int) -> list[models.RequestOffer]:
    return (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.request_kind == "analysis",
            models.RequestOffer.request_id == int(analysis_id),
        )
        .order_by(models.RequestOffer.id.desc())
        .all()
    )


def _abap_analysis_hub_delivered_fields(row: models.AbapAnalysisRequest) -> dict[str, Any]:
    raw_pkg = parse_delivered_code_payload(getattr(row, "delivered_code_payload", None))
    has_pkg = bool(raw_pkg and delivered_package_has_body(raw_pkg))
    dc_ready = (getattr(row, "delivered_code_status", None) or "").strip() == "ready"
    txt = (getattr(row, "delivered_code_text", None) or "").strip()
    delivered_package = raw_pkg if has_pkg else None
    delivered_code_html = ""
    if dc_ready and txt and not has_pkg:
        delivered_code_html = _markdown_to_html(row.delivered_code_text or "")
    impl_html = ""
    test_html = ""
    if delivered_package:
        impl_html = _markdown_to_html(delivered_package.get("implementation_guide_md") or "")
        test_html = _markdown_to_html(delivered_package.get("test_scenarios_md") or "")
    has_delivered_preview = bool(dc_ready and (has_pkg or bool(txt)))
    return {
        "delivered_package": delivered_package,
        "delivered_code_html": delivered_code_html,
        "delivered_impl_guide_html": impl_html,
        "delivered_test_scenarios_html": test_html,
        "has_delivered_preview": has_delivered_preview,
    }


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
    requirement_text_format: str = "html",
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
        "requirement_text_format": (requirement_text_format or "html").strip().lower(),
        "program_id": program_id or "",
        "transaction_code": transaction_code or "",
        "sap_modules": list(sap_modules or []),
        "dev_types": list(dev_types or []),
        "notes": pad[:5],
    }


def _abap_form_dict_from_row(row: models.AbapAnalysisRequest) -> dict:
    notes = _notes_from_entries(_attachment_entries(row))[:5]
    fmt = (getattr(row, "requirement_text_format", None) or "plain").strip().lower()
    return _abap_form_dict(
        title=row.title or "",
        requirement_text=row.requirement_text or "",
        requirement_text_format=fmt,
        program_id=getattr(row, "program_id", None) or "",
        transaction_code=getattr(row, "transaction_code", None) or "",
        sap_modules=_split_csv_chips(getattr(row, "sap_modules", None)),
        dev_types=_split_csv_chips(getattr(row, "dev_types", None)),
        notes=notes,
    )


def _requirement_plain(row: models.AbapAnalysisRequest) -> str:
    return _requirement_body_plain(row, "abap")


def _has_requirement_context(row: models.AbapAnalysisRequest) -> bool:
    return requirement_has_body_context(row, "abap")


def _apply_requirement_body(
    row: models.AbapAnalysisRequest,
    user: models.User,
    req_raw: str,
    fmt: str,
) -> Optional[str]:
    return _apply_requirement_body_shared(row, user, req_raw, fmt, "abap")


def _ref_initial_from_raw(reference_code_json: str) -> Optional[dict]:
    if not reference_code_json or not str(reference_code_json).strip():
        return None
    s = str(reference_code_json).strip()
    if len(s.encode("utf-8")) > MAX_REFERENCE_CODE_BYTES:
        return None
    try:
        data = json.loads(s)
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
        return q.filter(
            or_(
                models.AbapAnalysisRequest.user_id == user.id,
                abap_analysis_consultant_read_scope(user.id),
            )
        )
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


def _get_abap_row_for_requirement_media(
    db: Session, user: models.User, req_id: int
) -> Optional[models.AbapAnalysisRequest]:
    """요구사항 인라인·캡처 이미지 — 상세·요청 Console(읽기 전용)과 동일한 조회 범위."""
    if getattr(user, "is_admin", False) or getattr(user, "is_consultant", False):
        return (
            db.query(models.AbapAnalysisRequest)
            .filter(models.AbapAnalysisRequest.id == req_id)
            .first()
        )
    return _get_abap_row_readable(db, user, req_id)


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


def _screenshot_entries(row: models.AbapAnalysisRequest) -> list[dict]:
    return _screenshot_entries_from_row(row)


def _set_screenshots(row: models.AbapAnalysisRequest, entries: list[dict]) -> None:
    row.requirement_screenshots_json = requirement_screenshot_entries_to_json(entries)


def _screenshot_entries_for_template(
    row: Optional[models.AbapAnalysisRequest],
    *,
    req_id: Optional[int] = None,
) -> list[dict]:
    entries = _screenshot_entries(row) if row else []
    if not req_id:
        return entries
    out: list[dict] = []
    for i, ent in enumerate(entries):
        d = dict(ent)
        d["preview_url"] = f"/abap-analysis/{req_id}/requirement-screenshot?idx={i}"
        out.append(d)
    return out


def _merge_llm_digests(file_entries: list[dict], screenshot_entries: list[dict]) -> str:
    parts: list[str] = []
    d1 = build_attachment_llm_digest(file_entries or [], max_total_chars=12_000)
    if d1.strip():
        parts.append(d1.strip())
    d2 = build_requirement_screenshots_llm_digest(screenshot_entries or [])
    if d2.strip():
        parts.append(d2.strip())
    combined = "\n\n".join(parts)
    if len(combined) > 24_000:
        combined = combined[:24_000] + "\n…(컨텍스트 상한)…"
    return combined


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
    screenshot_entries: Optional[list[dict]] = None,
    sap_modules: Optional[List[str]] = None,
    dev_types: Optional[List[str]] = None,
) -> dict:
    from ..agents.free_crew import analyze_code_for_library, augment_abap_analysis_with_requirement

    att = attachment_entries if attachment_entries else []
    shots = screenshot_entries if screenshot_entries else []
    digest = _merge_llm_digests(att, shots)

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
    draft_saved: bool = False,
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
                key=lambda m: (
                    followup_created_at_sort_key(m, fallback=row_w.created_at),
                    getattr(m, "id", 0) or 0,
                ),
            )
            turns = _pair_abap_followup_turns(follow_msgs)
            eff = _effective_abap_source(row_w).strip()
            snap_f = ai_inquiry_snapshot(db, user, "analysis", row_w.id)
            ai_inquiry = {
                "mode": "live",
                "float_id": "abap-followup-chat",
                "size_key": "abap-followup-chat-size",
                "post_url": f"/abap-analysis/{row_w.id}/chat",
                "return_to": "edit",
                "followup_turns": turns,
                "chat_error": form_chat_err,
                "chat_limit_reached": snap_f["reached"],
                "max_turns": snap_f["max_turns_display"],
                "header_i18n": "chat.abapHeaderTitle",
                "context_i18n": "chat.abapContextHelp",
                "form_ready": bool(eff) or _has_requirement_context(row_w),
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
            "draft_saved": draft_saved,
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

    if user:
        admin_view = False
        consultant_matched = consultant_menu_matched_scope(user)
        cnt, _b = abap_analysis_menu_aggregate(
            db, admin=admin_view, user_id=user.id, consultant_matched=consultant_matched
        )
        menu_counts = cnt
        menu_total_rows = sum(menu_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft"))
        presets = menu_landing_preset_params(request.query_params)
        menu_tile_links = {
            k: menu_landing_url("/abap-analysis", presets, k) for k in TILE_ORDER_WITH_ALL
        }
        show_request_owner = consultant_matched
        if selected_bucket:
            filtered_rows = filtered_abap_analysis_menu_rows(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
                consultant_matched=consultant_matched,
            )

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
    requirement_text_format: str = Form("html"),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    title_raw = title or ""
    title_clean = (title_raw.strip())[:TITLE_MAX_LEN]
    req_raw = requirement_text or ""
    req_fmt = (requirement_text_format or "html").strip().lower()
    req_for_validate = (
        html_to_plain_text(req_raw) if is_html_format(req_fmt) else req_raw.strip()
    )
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    ref_initial = _ref_initial_from_raw(reference_code_json)
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_state() -> dict:
        return _abap_form_dict(
            title=title_raw,
            requirement_text=req_raw,
            requirement_text_format=req_fmt,
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
        req_for_validate,
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

    qerr = try_consume_monthly(db, user, METRIC_DEV_REQUEST, 1)
    if qerr == "disabled":
        return _bad("subscription_dev_request_disabled")
    if qerr == "monthly_limit":
        return _bad("subscription_dev_request_limit")

    if not is_draft_save:
        if len(title_clean) < MIN_TITLE_LEN:
            return _bad("need_title")
        if not norm_ref:
            return _bad("need_reference_code")
        if len(src) < MIN_ABAP_SOURCE_LEN:
            return _bad("code_too_short")

    row = models.AbapAnalysisRequest(
        user_id=user.id,
        title=title_clean,
        program_id=pid,
        transaction_code=tc,
        sap_modules=",".join(sap_modules) if sap_modules else "",
        dev_types=",".join(dev_types) if dev_types else "",
        requirement_text="",
        requirement_text_format="plain",
        reference_code_payload=norm_ref,
        source_code=src,
        analysis_json=None,
        is_analyzed=False,
        is_draft=is_draft_save,
    )
    _set_attachments(row, att_entries)
    db.add(row)
    try:
        db.flush()
        body_err = _apply_requirement_body(row, user, req_raw, req_fmt)
        if body_err:
            db.rollback()
            return _bad(body_err)
        if not is_draft_save:
            analysis = _run_analysis(
                _requirement_plain(row),
                src,
                att_entries,
                screenshot_entries=_screenshot_entries(row),
                sap_modules=sap_modules,
                dev_types=dev_types,
            )
            analyzed = not bool(analysis.get("error"))
            row.analysis_json = json.dumps(analysis, ensure_ascii=False)
            row.is_analyzed = analyzed
            row.is_draft = False
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    if is_draft_save:
        return RedirectResponse(
            url=f"/abap-analysis/{row.id}/edit?draft_saved=1",
            status_code=302,
        )
    return RedirectResponse(url=f"/abap-analysis/{row.id}", status_code=302)


@router.post("/{req_id}/duplicate-request")
def abap_analysis_duplicate_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """본인 분석 요청의 입력 필드·첨부·참고 코드만 복사한 새 임시저장 건을 만듭니다."""
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if monthly_quota_exceeded(db, user, METRIC_REQUEST_DUPLICATE, 1):
        return RedirectResponse(url=f"/abap-analysis/{req_id}?quota_err=duplicate_limit", status_code=302)
    if monthly_quota_exceeded(db, user, METRIC_DEV_REQUEST, 1):
        return RedirectResponse(url=f"/abap-analysis/{req_id}?quota_err=dev_request_limit", status_code=302)
    consume_monthly(db, user, METRIC_REQUEST_DUPLICATE, 1)
    consume_monthly(db, user, METRIC_DEV_REQUEST, 1)
    att = duplicate_attachment_entries(_attachment_entries(row), user_id=user.id)
    shots = duplicate_requirement_screenshots(_screenshot_entries(row), user_id=user.id)
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
        requirement_text_format=getattr(row, "requirement_text_format", None) or "plain",
        reference_code_payload=row.reference_code_payload,
        source_code=src,
        is_draft=True,
        is_analyzed=False,
        analysis_json=None,
        workflow_rfp_id=None,
        improvement_request_text=None,
    )
    _set_attachments(new_row, att)
    _set_screenshots(new_row, shots)
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return RedirectResponse(
        url=f"/abap-analysis/{new_row.id}/edit?draft_saved=1",
        status_code=302,
    )


@router.get("/{req_id}/edit", response_class=HTMLResponse)
def abap_analysis_edit_form(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_request_for_user(db, user, req_id)
    if not row or not row.is_draft:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    chat_err = (request.query_params.get("chat_err") or "").strip() or None
    draft_saved = (request.query_params.get("draft_saved") or "").strip() == "1"
    return _form_template_response(
        request,
        user,
        db,
        error=None,
        form=_abap_form_dict_from_row(row),
        ref_code_initial=_ref_initial_from_row(row),
        edit_row=row,
        draft_saved=draft_saved,
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
    requirement_text_format: str = Form("html"),
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
    req_fmt = (requirement_text_format or "html").strip().lower()
    req_for_validate = (
        html_to_plain_text(req_raw) if is_html_format(req_fmt) else req_raw.strip()
    )
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
            requirement_text_format=req_fmt,
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
        req_for_validate,
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

    if not is_draft_save:
        if len(title_clean) < MIN_TITLE_LEN:
            return _bad("need_title")
        if not norm_ref:
            return _bad("need_reference_code")
        if len(src) < MIN_ABAP_SOURCE_LEN:
            return _bad("code_too_short")

    row.title = title_clean
    row.program_id = pid
    row.transaction_code = tc
    row.sap_modules = ",".join(sap_modules) if sap_modules else ""
    row.dev_types = ",".join(dev_types) if dev_types else ""
    row.reference_code_payload = norm_ref
    row.source_code = src
    _set_attachments(row, merged_att)

    body_err = _apply_requirement_body(row, user, req_raw, req_fmt)
    if body_err:
        return _bad(body_err)

    if is_draft_save:
        row.is_draft = True
        row.is_analyzed = False
        row.analysis_json = None
    else:
        analysis = _run_analysis(
            _requirement_plain(row),
            src,
            merged_att,
            screenshot_entries=_screenshot_entries(row),
            sap_modules=sap_modules,
            dev_types=dev_types,
        )
        analyzed = not bool(analysis.get("error"))
        row.analysis_json = json.dumps(analysis, ensure_ascii=False)
        row.is_analyzed = analyzed
        row.is_draft = False

    db.add(row)
    db.commit()
    if is_draft_save:
        return RedirectResponse(
            url=f"/abap-analysis/{row.id}/edit?draft_saved=1",
            status_code=302,
        )
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
    wf_rid = getattr(row, "workflow_rfp_id", None)
    if getattr(user, "is_admin", False) or (
        readonly_console and getattr(user, "is_consultant", False)
    ) or (
        wf_rid
        and consultant_is_matched_on_request(
            db,
            consultant_user_id=user.id,
            request_kind="rfp",
            request_id=int(wf_rid),
        )
    ) or consultant_is_matched_on_request(
        db,
        consultant_user_id=user.id,
        request_kind="analysis",
        request_id=int(row.id),
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

    bucket = abap_analysis_menu_bucket(row)
    if bucket == "proposal":
        ro_suffix = "#abap-phase-proposal"
    elif bucket == "delivery":
        ro_suffix = "#abap-phase-fs"
    else:
        ro_suffix = ""
    hub_readonly_return_url = (
        f"/abap-analysis/{row.id}/console-readonly{ro_suffix}" if readonly_console else None
    )

    code_asset_unlocked = user_may_copy_download_request_assets(
        db,
        user,
        request_kind="analysis",
        request_id=int(row.id),
        owner_user_id=int(row.user_id),
    )

    req_ctx = _requirement_display_ctx(row, "abap", row.id)

    ana_ist = (getattr(row, "interview_status", None) or "pending").strip()
    ana_hub_proposal_generating = ana_ist == "generating_proposal"
    ana_proposal_html = ""
    if ana_ist == "completed" and (getattr(row, "proposal_text", None) or "").strip():
        ana_proposal_html = _markdown_to_html(wrap_unbracketed_agent_names(row.proposal_text or ""))

    ana_fs_stat = (getattr(row, "fs_status", None) or "none").strip() or "none"
    ana_fs_html = ""
    if ana_fs_stat == "ready" and (getattr(row, "fs_text", None) or "").strip():
        ana_fs_html = _markdown_to_html(row.fs_text or "")

    offers_raw = _analysis_offer_rows(db, row.id)
    vis_offers = visible_request_offers_for_viewer(
        offers_raw,
        viewer=user,
        owner_user_id=int(row.user_id),
        privileged_operator=bool(getattr(user, "is_admin", False)),
    )
    ana_hub: dict[str, Any] = {
        "ana_hub_proposal_generating": ana_hub_proposal_generating,
        "ana_proposal_html": ana_proposal_html,
        "ana_interview_status": ana_ist,
        "request_offers": vis_offers,
        "request_offer_can_match": bool(
            user and int(user.id) == int(row.user_id) and not readonly_console
        ),
        "request_offer_profile_url_builder": lambda oid, rid=row.id: f"/abap-analysis/{rid}/offers/{int(oid)}/profile",
        "request_offer_match_url_builder": lambda oid, rid=row.id: f"/abap-analysis/{rid}/offers/{int(oid)}/match",
        "request_offer_inquiry_url_builder": lambda oid, rid=row.id: f"/abap-analysis/{rid}/offers/{int(oid)}/inquiry",
        "request_offer_inquiry_reply_url_builder": lambda oid, rid=row.id: f"/abap-analysis/{rid}/offers/{int(oid)}/inquiry-reply",
        "request_offer_inquiries_by_offer_id": inquiries_by_offer_id(db, [int(o.id) for o in vis_offers]),
        "request_offer_can_inquire": bool(user and int(user.id) == int(row.user_id) and not readonly_console),
        "offer_inquiry_request_detail_url": public_request_url(
            request, f"/abap-analysis/{row.id}#abap-phase-proposal"
        ),
        "offer_inquiry_err": (request.query_params.get("offer_inquiry_err") or "").strip(),
        "ana_fs_stat": (getattr(row, "fs_status", None) or "none").strip() or "none",
        "ana_dc_stat": (getattr(row, "delivered_code_status", None) or "none").strip() or "none",
        "ana_fs_busy": (getattr(row, "fs_status", None) or "").strip() == "generating",
        "ana_dc_busy": (getattr(row, "delivered_code_status", None) or "").strip() == "generating",
        "ana_gen_busy": ((getattr(row, "fs_status", None) or "").strip() == "generating")
        or ((getattr(row, "delivered_code_status", None) or "").strip() == "generating"),
        "ana_can_request_proposal": bool(
            int(user.id) == int(row.user_id)
            and not readonly_console
            and row.is_analyzed
            and not (row.proposal_text or "").strip()
            and ana_ist != "generating_proposal"
        ),
        "ana_proposal_scripts": bool(ana_proposal_html)
        and (not ana_hub_proposal_generating)
        and (not readonly_console),
        "ana_has_delivered_zip": rfp_delivered_body_ready(row),
        "offer_inquiry_ok": (request.query_params.get("offer_inquiry_ok") or "").strip() == "1",
        "offer_inquiry_reply_ok": (request.query_params.get("offer_inquiry_reply_ok") or "").strip()
        == "1",
        "offer_inquiry_reply_err": (request.query_params.get("offer_inquiry_reply_err") or "").strip(),
        "ana_fs_html": ana_fs_html,
        **_abap_analysis_hub_delivered_fields(row),
    }

    if readonly_console:
        return {
            "request": request,
            "user": user,
            "row": row,
            "analysis": analysis,
            "attachment_entries": _attachment_entries(row),
            **req_ctx,
            "owner": owner,
            "code_asset_unlocked": code_asset_unlocked,
            "source_program_groups": program_groups,
            **ana_hub,
        }

    followup_messages = sorted(
        list(row.followup_messages or []),
        key=lambda m: (
            followup_created_at_sort_key(m, fallback=row.created_at),
            getattr(m, "id", 0) or 0,
        ),
    )
    followup_turns = _pair_abap_followup_turns(followup_messages)
    chat_enabled = (not row.is_draft) and bool(eff_src.strip())
    snap_d = ai_inquiry_snapshot(db, user, "analysis", row.id)
    chat_limit_reached = snap_d["reached"]
    chat_error = (request.query_params.get("chat_err") or "").strip() or None
    wf_err = (request.query_params.get("wf_err") or "").strip() or None
    qe = (request.query_params.get("quota_err") or "").strip()
    subscription_quota_flash = None
    if qe == "duplicate_limit":
        subscription_quota_flash = "이번 달(UTC) 요청 복사 한도에 도달했습니다."
    elif qe == "dev_request_limit":
        subscription_quota_flash = "이번 달(UTC) 개발 요청 생성 한도에 도달했습니다."
    elif qe == "dev_request_disabled":
        subscription_quota_flash = "현재 플랜에서 개발 요청을 더 만들 수 없습니다."
    elif qe == "dev_proposal_limit":
        subscription_quota_flash = "이번 달(UTC) 개발 제안서 생성 한도에 도달했습니다."
    elif qe == "dev_proposal_disabled":
        subscription_quota_flash = "현재 플랜에서 개발 제안서 생성을 사용할 수 없습니다."
    elif qe == "proposal_regen_limit":
        subscription_quota_flash = "이 요청에서 제안서 재생성 허용 횟수에 도달했습니다."
    elif qe == "proposal_regen_disabled":
        subscription_quota_flash = "현재 플랜에서 제안서 재생성을 사용할 수 없습니다."
    return {
        "request": request,
        "user": user,
        "row": row,
        "analysis": analysis,
        "attachment_entries": _attachment_entries(row),
        **req_ctx,
        "owner": owner,
        "code_asset_unlocked": code_asset_unlocked,
        "followup_turns": followup_turns,
        "chat_enabled": chat_enabled,
        "chat_limit_reached": chat_limit_reached,
        "chat_error": chat_error,
        "wf_err": wf_err,
        "subscription_quota_flash": subscription_quota_flash,
        "source_program_groups": program_groups,
        "max_followup_user_turns": snap_d["max_turns_display"],
        "abap_ai_inquiry_unlimited": snap_d["unlimited"],
        "abap_followup_cap": snap_d["cap"],
        "hub_readonly_return_url": hub_readonly_return_url,
        **ana_hub,
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
def abap_analysis_improvement_proposal_post(req_id: int, request: Request, db: Session = Depends(get_db)):
    """레거시 URL — 제안서 단계로 이동."""
    _require_user(request, db)
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)


@router.post("/{req_id}/proposal/request-now")
def abap_analysis_request_proposal_now(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _query_for_user(db, user).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if (row.interview_status or "") == "generating_proposal":
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    if (row.interview_status or "") == "completed" and (row.proposal_text or "").strip():
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    if not row.is_analyzed:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-analysis", status_code=302)
    err_p = try_consume_monthly(db, user, METRIC_DEV_PROPOSAL, 1)
    if err_p == "disabled":
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?quota_err=dev_proposal_disabled#abap-phase-proposal",
            status_code=302,
        )
    if err_p == "monthly_limit":
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?quota_err=dev_proposal_limit#abap-phase-proposal",
            status_code=302,
        )
    row.interview_status = "generating_proposal"
    db.add(row)
    db.commit()
    background_tasks.add_task(run_abap_analysis_proposal_background, row.id)
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)


@router.post("/{req_id}/proposal/regenerate")
def abap_analysis_regenerate_proposal(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _query_for_user(db, user).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    err_r = try_consume_per_request(db, user, METRIC_DEV_PROPOSAL_REGEN, "analysis", req_id, 1)
    if err_r == "disabled":
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?quota_err=proposal_regen_disabled#abap-phase-proposal",
            status_code=302,
        )
    if err_r == "per_request_limit":
        return RedirectResponse(
            url=f"/abap-analysis/{req_id}?quota_err=proposal_regen_limit#abap-phase-proposal",
            status_code=302,
        )
    row.interview_status = "generating_proposal"
    row.proposal_text = None
    db.add(row)
    db.commit()
    background_tasks.add_task(run_abap_analysis_proposal_background, row.id)
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)


@router.get("/{req_id}/proposal/status")
def abap_analysis_proposal_status(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
    if not row:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({"status": (row.interview_status or "pending")})


@router.get("/{req_id}/delivered-code/download")
def abap_analysis_delivered_code_download(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = _get_abap_row_readable(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="analysis",
        request_id=req_id,
        owner_user_id=int(row.user_id),
    ):
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if not rfp_delivered_body_ready(row):
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    pkg = parse_delivered_code_payload(getattr(row, "delivered_code_payload", None))
    if pkg and delivered_package_has_body(pkg):
        buf = io.BytesIO()
        used_names: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "IMPLEMENTATION_GUIDE.md",
                (pkg.get("implementation_guide_md") or "").encode("utf-8"),
            )
            zf.writestr(
                "TEST_SCENARIOS.md",
                (pkg.get("test_scenarios_md") or "").encode("utf-8"),
            )
            for idx, sl in enumerate(pkg.get("slots") or []):
                if not isinstance(sl, dict):
                    continue
                base_fn = (str(sl.get("filename") or f"slot_{idx + 1}.abap")).strip() or f"slot_{idx + 1}.abap"
                fn = base_fn
                if fn in used_names:
                    stem = base_fn.rsplit(".", 1)[0] if "." in base_fn else base_fn
                    ext = base_fn.rsplit(".", 1)[-1] if "." in base_fn else "abap"
                    fn = f"{idx + 1:02d}_{stem}.{ext}"
                used_names.add(fn)
                zf.writestr(fn, (sl.get("source") or "").encode("utf-8"))
        body = buf.getvalue()
        fname = delivered_code_zip_basename(getattr(row, "program_id", None), getattr(row, "title", None))
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": content_disposition_attachment(fname)},
        )
    body = (row.delivered_code_text or "").encode("utf-8")
    fname = delivered_abap_download_basename(getattr(row, "program_id", None), getattr(row, "title", None))
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
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
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=303)
    chat_base = f"/abap-analysis/{req_id}/edit" if row.is_draft else f"/abap-analysis/{req_id}"
    eff_src = _effective_abap_source(row)
    if not eff_src.strip() and not _has_requirement_context(row):
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote('요구사항 또는 ABAP 코드가 없어 AI 문의를 시작할 수 없습니다.')}",
            status_code=303,
        )

    msg, verr = validate_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote(verr)}",
            status_code=303,
        )

    used_ai = get_ai_inquiry_used(db, user.id, "analysis", row.id)
    cap = ai_inquiry_snapshot(db, user, "analysis", row.id)["cap"]
    if ai_inquiry_limit_reached(cap, used_ai):
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
    if not getattr(user, "is_admin", False):
        record_ai_inquiry_user_turn(db, user.id, "analysis", row.id, ledger_after=used_ai + 1)
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
    req_row = db.query(models.AbapAnalysisRequest).filter(
        models.AbapAnalysisRequest.id == req_id,
        models.AbapAnalysisRequest.user_id == user.id,
    ).first()
    if not req_row:
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
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)
    if (offer.status or "") == "matched":
        offer.status = "offered"
        offer.matched_at = None
        offer.match_notice_pending = False
        db.add(offer)
        db.commit()
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)
    db.query(models.RequestOffer).filter(
        models.RequestOffer.request_kind == "analysis",
        models.RequestOffer.request_id == req_id,
    ).update(
        {"status": "offered", "matched_at": None, "match_notice_pending": False},
        synchronize_session=False,
    )
    offer.status = "matched"
    offer.matched_at = datetime.utcnow()
    offer.match_notice_pending = True
    db.add(offer)
    db.commit()
    title = (req_row.title or "").strip() or f"분석·개선 #{req_id}"
    c = offer.consultant
    if c:
        notify_consultant_request_matched(
            request=request,
            consultant=c,
            request_kind="analysis",
            request_id=req_id,
            request_title=title,
        )
    return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)


@router.post("/{req_id}/offers/{offer_id}/inquiry")
def abap_analysis_offer_inquiry_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    req_row = db.query(models.AbapAnalysisRequest).filter(
        models.AbapAnalysisRequest.id == req_id,
        models.AbapAnalysisRequest.user_id == user.id,
    ).first()
    if not req_row:
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
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)
    title = (req_row.title or "").strip() or f"분석·개선 #{req_id}"
    detail = public_request_url(request, f"/abap-analysis/{req_id}#abap-phase-proposal")
    err, _row = send_offer_inquiry_from_owner(
        db,
        request=request,
        author=user,
        offer=offer,
        consultant=offer.consultant,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = f"/abap-analysis/{req_id}#abap-phase-proposal"
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_ok=1", status_code=303)


@router.post("/{req_id}/offers/{offer_id}/inquiry-reply")
def abap_analysis_offer_inquiry_reply_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    return_hub: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    if not getattr(user, "is_consultant", False):
        return RedirectResponse(url="/", status_code=302)
    req_row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not req_row:
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
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)
    owner = db.query(models.User).filter(models.User.id == req_row.user_id).first()
    if not owner:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=303)
    title = (req_row.title or "").strip() or f"분석·개선 #{req_id}"
    detail = public_request_url(request, f"/abap-analysis/{req_id}#abap-phase-proposal")
    err, _row = send_consultant_offer_inquiry_reply(
        db,
        request=request,
        consultant=user,
        offer=offer,
        owner=owner,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = f"/abap-analysis/{req_id}#abap-phase-proposal"
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(
            url=f"{base}{sep}offer_inquiry_reply_err={quote(err)}", status_code=303
        )
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_ok=1", status_code=303)


@router.get("/{req_id}/offers/{offer_id}/profile")
def abap_analysis_offer_profile_download(
    req_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    req_row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == req_id).first()
    if not req_row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    if int(user.id) != int(req_row.user_id) and not getattr(user, "is_admin", False):
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
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
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    path = (getattr(offer.consultant, "consultant_profile_file_path", None) or "").strip()
    fname = (
        getattr(offer.consultant, "consultant_profile_file_name", None) or "consultant_profile"
    ).strip() or "consultant_profile"
    if not path:
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
        return RedirectResponse(url=r2_storage.presigned_get_url(ref, fname), status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url=f"/abap-analysis/{req_id}#abap-phase-proposal", status_code=302)
    return FileResponse(ref, filename=fname)


@router.get("/{req_id}/requirement-inline")
def abap_analysis_requirement_inline_image(
    req_id: int,
    request: Request,
    iid: str = "",
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_for_requirement_media(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    key = (iid or "").strip()
    if not key:
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    ent = resolve_inline_entry(row, key)
    return inline_image_response(
        ent=ent,
        redirect_url=f"/abap-analysis/{req_id}",
    )


@router.get("/{req_id}/requirement-screenshot")
def abap_analysis_requirement_screenshot(
    req_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    row = _get_abap_row_for_requirement_media(db, user, req_id)
    if not row:
        return RedirectResponse(url="/abap-analysis", status_code=302)
    entries = _screenshot_entries(row)
    if idx < 0 or idx >= len(entries):
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
    ent = entries[idx]
    path = ent.get("path")
    fname = ent.get("filename") or "screenshot.png"
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
    media = "image/png"
    low = fname.lower()
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        media = "image/jpeg"
    elif low.endswith(".webp"):
        media = "image/webp"
    return FileResponse(ref, media_type=media, filename=fname)


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
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="analysis",
        request_id=req_id,
        owner_user_id=int(row.user_id),
    ):
        return RedirectResponse(url=f"/abap-analysis/{req_id}", status_code=302)
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
    analysis = _run_analysis(
        _requirement_plain(row),
        eff_src,
        _attachment_entries(row),
        screenshot_entries=_screenshot_entries(row),
    )
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
    remove_requirement_screenshots(_screenshot_entries(row))
    db.delete(row)
    db.commit()
    return RedirectResponse(url="/abap-analysis", status_code=302)
