"""SAP 연동 개발 요청 라우터 (VBA, Python, 배치, API 등)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any, List
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from .. import models, auth
from ..abap_followup_chat import MAX_USER_TURNS_PER_REQUEST as INT_CHAT_MAX_USER
from .abap_analysis_router import _pair_abap_followup_turns as _pair_integration_followup_turns
from ..attachment_context import build_attachment_llm_digest
from ..database import get_db
from ..rfp_reference_code import normalize_reference_code_payload, reference_code_program_groups_for_tabs
from ..menu_landing import (
    DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    filtered_integration_menu_rows,
    integration_menu_aggregate,
    menu_landing_preset_params,
    menu_landing_url,
    parse_slashed_date,
    standard_menu_bucket_meta,
)
from ..rfp_landing import (
    DEFAULT_SERVICE_ABAP_INTRO_MD_KO,
    filtered_rfp_list_for_landing,
    rfp_landing_aggregate,
)
from ..devtype_catalog import (
    active_integration_impl_devtypes,
    integration_impl_allowed_codes,
    integration_impl_labels_map,
)
from ..templates_config import templates
from ..writing_guides_service import get_writing_guides_by_lang_bundle
from ..paid_tier import user_can_operate_delivery
from ..integration_followup_chat import (
    generate_integration_followup_reply,
    integration_request_llm_summary,
    validate_integration_user_message,
)
from ..agent_display import wrap_unbracketed_agent_names
from ..integration_hub import integration_hub_url, normalize_integration_hub_phase
from ..integration_interview_service import serve_integration_interview_workspace
from ..routers.interview_router import _markdown_to_html, _messages_to_list
from .rfp_router import (
    MAX_RFP_ATTACHMENTS,
    _build_attachment_entries_from_uploads,
    _get_modules_devtypes,
    _remove_stored_file,
    duplicate_attachment_entries,
    r2_storage,
)

router = APIRouter()


def _integration_impl_ui_ctx(db: Session) -> dict:
    """연동 구현 형태: 폼 칩(순서) + 배지용 코드→라벨 맵 + 작성 가이드 맵."""
    return {
        "integration_impl_devtypes": active_integration_impl_devtypes(db),
        "impl_labels": integration_impl_labels_map(db),
        "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
    }


def _attachment_entries(ir: models.IntegrationRequest) -> list[dict]:
    if not ir.attachments_json:
        return []
    try:
        data = json.loads(ir.attachments_json)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("path")]
    except Exception:
        pass
    return []


def _set_attachments(ir: models.IntegrationRequest, entries: list[dict]) -> None:
    if not entries:
        ir.attachments_json = None
        return
    ir.attachments_json = json.dumps(entries, ensure_ascii=False)


@router.get("/services/abap", response_class=HTMLResponse)
def services_abap_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    intro_md = (raw.get("service_abap_intro_md_ko") or "").strip() or DEFAULT_SERVICE_ABAP_INTRO_MD_KO
    intro_html = _markdown_to_html(intro_md)

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

    privileged = bool(user and user_can_operate_delivery(user))

    rfp_total_rows = 0
    rfp_landing_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    svc_abap_tile_links: dict[str, str] = {}
    rfps_filtered: list = []

    show_rfp_owner = False
    if user:
        admin_view = privileged
        show_rfp_owner = admin_view

        cnt, _buckets = rfp_landing_aggregate(db, admin=admin_view, user_id=user.id)
        rfp_landing_counts = cnt
        rfp_total_rows = sum(
            rfp_landing_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft")
        )
        presets = menu_landing_preset_params(request.query_params)
        svc_abap_tile_links = {
            k: menu_landing_url("/services/abap", presets, k) for k in TILE_ORDER_WITH_ALL
        }

        if selected_bucket:
            rfps_filtered = filtered_rfp_list_for_landing(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )

    bucket_meta = standard_menu_bucket_meta()
    return templates.TemplateResponse(
        request,
        "services_abap.html",
        {
            "request": request,
            "user": user,
            "service_abap_intro_html": intro_html,
            "rfp_landing_counts": rfp_landing_counts,
            "rfp_total_rows": rfp_total_rows,
            "svc_abap_filtered_rfps": rfps_filtered if user else [],
            "svc_abap_tile_links": svc_abap_tile_links,
            "svc_abap_tile_order": list(TILE_ORDER_WITH_ALL),
            "selected_svc_abap_bucket": selected_bucket,
            "svc_abap_show_list": bool(user and selected_bucket),
            "svc_abap_search_title": title_search or "",
            "svc_abap_date_from_raw": date_from_raw or "",
            "svc_abap_date_to_raw": date_to_raw or "",
            "show_rfp_owner": show_rfp_owner,
            "bucket_meta": bucket_meta,
        },
    )


@router.get("/integration", response_class=HTMLResponse)
def integration_landing(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)

    raw_settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    intro_md = (raw_settings.get("service_integration_intro_md_ko") or "").strip() or DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO
    service_integration_intro_html = _markdown_to_html(intro_md)

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

    privileged = bool(user and user_can_operate_delivery(user))
    menu_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    menu_total_rows = 0
    menu_tile_links: dict[str, str] = {}
    filtered_rows: list[models.IntegrationRequest] = []
    show_request_owner = bool(user and privileged)

    if user:
        admin_view = privileged
        cnt, _b = integration_menu_aggregate(db, admin=admin_view, user_id=user.id)
        menu_counts = cnt
        menu_total_rows = sum(menu_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft"))
        presets = menu_landing_preset_params(request.query_params)
        menu_tile_links = {k: menu_landing_url("/integration", presets, k) for k in TILE_ORDER_WITH_ALL}
        if selected_bucket:
            filtered_rows = filtered_integration_menu_rows(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )

    bucket_meta = standard_menu_bucket_meta()
    return templates.TemplateResponse(
        request,
        "integration_landing.html",
        {
            "request": request,
            "user": user,
            "service_integration_intro_html": service_integration_intro_html,
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
            "menu_landing_form_action": "/integration",
            **_integration_impl_ui_ctx(db),
        },
    )


@router.get("/integration/new", response_class=HTMLResponse)
def integration_new_form(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/integration/new", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    return templates.TemplateResponse(
        request,
        "integration_form.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "devtypes": devtypes,
            "error": None,
            "form": None,
            "edit_ir": None,
            "integration_ref_code_initial": None,
            "attachment_entries": None,
            "ai_inquiry": {
                "mode": "teaser",
                "float_id": "integration-new-ai-teaser",
                "teaser_i18n": "chat.formAiTeaserInt",
            },
            **_integration_impl_ui_ctx(db),
        },
    )


@router.post("/integration/new")
async def integration_new_submit(
    request: Request,
    title: str = Form(""),
    impl_types: List[str] = Form(default=[]),
    sap_touchpoints: str = Form(""),
    environment_notes: str = Form(""),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    reference_code_json: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_dict():
        return {
            "title": title,
            "impl_types": impl_types,
            "sap_touchpoints": sap_touchpoints,
            "environment_notes": environment_notes,
            "description": description,
            "notes": notes_in,
        }

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "too_many_attachments",
                "form": _form_dict(),
            },
            status_code=400,
        )

    att_entries: list[dict] = []
    if n_uploads:
        att_entries, err_a = await _build_attachment_entries_from_uploads(
            user.id, attachments, notes_in
        )
        if err_a:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": err_a,
                    "form": _form_dict(),
                },
                status_code=400,
            )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "reference_code_too_large",
                "form": _form_dict(),
            },
            status_code=400,
        )

    allowed_impl = integration_impl_allowed_codes(db)
    impl_clean = [x for x in impl_types if x in allowed_impl]
    if not is_draft_save and not impl_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_impl_types",
                "form": _form_dict(),
            },
            status_code=400,
        )
    title_clean = (title or "").strip()
    if not is_draft_save and not title_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_title",
                "form": _form_dict(),
            },
            status_code=400,
        )
    display_title = title_clean or "SAP 연동 개발 요청 (임시)"
    ir = models.IntegrationRequest(
        user_id=user.id,
        title=display_title,
        impl_types=",".join(impl_clean) if impl_clean else "",
        sap_touchpoints=sap_touchpoints.strip() or None,
        environment_notes=environment_notes.strip() or None,
        security_notes=None,
        description=description.strip() or None,
        reference_code_payload=norm_ref,
        status="draft" if is_draft_save else "submitted",
        interview_status="pending",
    )
    _set_attachments(ir, att_entries)
    db.add(ir)
    db.commit()
    db.refresh(ir)
    if is_draft_save:
        return RedirectResponse(url=f"/integration/{ir.id}/edit", status_code=302)
    return RedirectResponse(url=f"/integration/{ir.id}", status_code=302)


@router.post("/integration/{req_id}/duplicate-request")
def integration_duplicate_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """본인 연동 요청을 초안으로 복사한 뒤 수정 폼으로 이동합니다."""
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
    entries = duplicate_attachment_entries(_attachment_entries(ir), user_id=user.id)
    title = (ir.title or "").strip()
    if title and not title.endswith(" (복사)"):
        title = f"{title} (복사)"
    new_ir = models.IntegrationRequest(
        user_id=user.id,
        title=title or "복사된 연동 요청",
        impl_types=ir.impl_types,
        sap_touchpoints=ir.sap_touchpoints,
        environment_notes=ir.environment_notes,
        security_notes=ir.security_notes,
        description=ir.description,
        reference_code_payload=ir.reference_code_payload,
        status="draft",
        interview_status="pending",
        workflow_rfp_id=None,
        improvement_request_text=None,
    )
    _set_attachments(new_ir, entries)
    db.add(new_ir)
    db.commit()
    db.refresh(new_ir)
    return RedirectResponse(url=f"/integration/{new_ir.id}/edit", status_code=302)


@router.post("/integration/{req_id}/delete")
def integration_delete(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not user.is_admin:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = q.first()
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    fs_s = (getattr(ir, "fs_status", None) or "none").strip().lower() or "none"
    if fs_s == "ready" and (getattr(ir, "fs_text", None) or "").strip():
        return RedirectResponse(url=f"/integration/{req_id}?delete_blocked=fs", status_code=302)
    for ent in _attachment_entries(ir):
        _remove_stored_file(ent.get("path"))
    db.delete(ir)
    db.commit()
    return RedirectResponse(url="/integration", status_code=302)


@router.get("/integration/{req_id}/edit", response_class=HTMLResponse)
def integration_edit_form(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(
            url=f"/login?next={quote('/integration/' + str(req_id) + '/edit')}",
            status_code=302,
        )
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.followup_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir or (ir.status or "").strip().lower() != "draft":
        return RedirectResponse(url="/integration", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    ents = _attachment_entries(ir)
    notes: list[str] = []
    for i in range(5):
        notes.append((ents[i].get("note") or "") if i < len(ents) else "")
    raw_impl = [t.strip() for t in (ir.impl_types or "").split(",") if t.strip()]
    form = {
        "title": ir.title or "",
        "impl_types": raw_impl,
        "sap_touchpoints": ir.sap_touchpoints or "",
        "environment_notes": ir.environment_notes or "",
        "description": ir.description or "",
        "notes": notes,
    }
    ref_init = None
    if ir.reference_code_payload:
        try:
            ref_init = json.loads(ir.reference_code_payload)
        except Exception:
            ref_init = None
    follow_msgs = sorted(
        list(ir.followup_messages or []),
        key=lambda m: (m.created_at or ir.created_at),
    )
    followup_turns = _pair_integration_followup_turns(follow_msgs)
    n_fu = sum(1 for m in follow_msgs if (m.role or "") == "user")
    chat_err = (request.query_params.get("chat_err") or "").strip() or None
    ai_inquiry = {
        "mode": "live",
        "float_id": "integration-followup-chat",
        "size_key": "integration-followup-chat-size",
        "post_url": f"/integration/{ir.id}/chat",
        "return_to": "edit",
        "followup_turns": followup_turns,
        "chat_error": chat_err,
        "chat_limit_reached": n_fu >= INT_CHAT_MAX_USER,
        "max_turns": INT_CHAT_MAX_USER,
        "header_i18n": "chat.intHeaderTitle",
        "context_i18n": "chat.intContextHelp",
        "form_ready": True,
    }
    return templates.TemplateResponse(
        request,
        "integration_form.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "devtypes": devtypes,
            **_integration_impl_ui_ctx(db),
            "error": None,
            "form": form,
            "edit_ir": ir,
            "integration_ref_code_initial": ref_init,
            "attachment_entries": ents,
            "ai_inquiry": ai_inquiry,
        },
    )


@router.post("/integration/{req_id}/edit")
async def integration_edit_submit(
    req_id: int,
    request: Request,
    title: str = Form(""),
    impl_types: List[str] = Form(default=[]),
    sap_touchpoints: str = Form(""),
    environment_notes: str = Form(""),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    reference_code_json: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir or (ir.status or "").strip().lower() != "draft":
        return RedirectResponse(url="/integration", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_dict():
        return {
            "title": title,
            "impl_types": impl_types,
            "sap_touchpoints": sap_touchpoints,
            "environment_notes": environment_notes,
            "description": description,
            "notes": notes_in,
        }

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "too_many_attachments",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": _attachment_entries(ir),
            },
            status_code=400,
        )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        ref_init = None
        if (reference_code_json or "").strip():
            try:
                ref_init = json.loads(reference_code_json)
            except Exception:
                ref_init = None
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "reference_code_too_large",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": ref_init,
                "attachment_entries": _attachment_entries(ir),
            },
            status_code=400,
        )

    merged_att = list(_attachment_entries(ir))
    if n_uploads:
        new_e, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": err_a,
                    "form": _form_dict(),
                    "edit_ir": ir,
                    "integration_ref_code_initial": None,
                    "attachment_entries": merged_att,
                },
                status_code=400,
            )
        merged_att = merged_att + (new_e or [])
        if len(merged_att) > MAX_RFP_ATTACHMENTS:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": "too_many_attachments",
                    "form": _form_dict(),
                    "edit_ir": ir,
                    "integration_ref_code_initial": None,
                    "attachment_entries": merged_att,
                },
                status_code=400,
            )

    allowed_impl = integration_impl_allowed_codes(db)
    impl_clean = [x for x in impl_types if x in allowed_impl]
    if not is_draft_save and not impl_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_impl_types",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": merged_att,
            },
            status_code=400,
        )
    title_clean = (title or "").strip()
    if not is_draft_save and not title_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_title",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": merged_att,
            },
            status_code=400,
        )

    ir.title = title_clean or ir.title or "SAP 연동 개발 요청 (임시)"
    ir.impl_types = ",".join(impl_clean) if impl_clean else ""
    ir.sap_touchpoints = sap_touchpoints.strip() or None
    ir.environment_notes = environment_notes.strip() or None
    ir.security_notes = None
    ir.description = description.strip() or None
    ir.reference_code_payload = norm_ref
    if is_draft_save:
        ir.status = "draft"
    else:
        ir.status = "submitted"
        ir.interview_status = "pending"
    _set_attachments(ir, merged_att)
    db.add(ir)
    db.commit()
    if is_draft_save:
        return RedirectResponse(url=f"/integration/{ir.id}/edit", status_code=302)
    return RedirectResponse(url=f"/integration/{ir.id}", status_code=302)


@router.get("/integration/{req_id}/generation-status")
def integration_generation_status(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    privileged = user_can_operate_delivery(user)
    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not privileged:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = q.first()
    if not ir:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse(
        {
            "fs_status": getattr(ir, "fs_status", None) or "none",
            "delivered_code_status": getattr(ir, "delivered_code_status", None) or "none",
            "fs_job_log": getattr(ir, "fs_job_log", None) or "",
            "delivered_job_log": getattr(ir, "delivered_job_log", None) or "",
            "fs_error": getattr(ir, "fs_error", None) or "",
            "delivered_code_error": getattr(ir, "delivered_code_error", None) or "",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/integration/{req_id}", response_class=HTMLResponse)
def integration_detail(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    phase: str | None = None,
    view: str | None = None,
    db: Session = Depends(get_db),
):
    """연동 개발 통합 상세 — 요청·인터뷰·제안서·FS·구현 가이드."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    requested_phase = normalize_integration_hub_phase(phase)
    view_summary = (view or "").strip().lower() == "summary" and requested_phase == "interview"
    privileged = user_can_operate_delivery(user)

    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not privileged:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = (
        q.options(
            joinedload(models.IntegrationRequest.followup_messages),
            joinedload(models.IntegrationRequest.workflow_rfp),
            joinedload(models.IntegrationRequest.interview_messages),
        ).first()
    )
    if not ir:
        return RedirectResponse(url="/", status_code=302)

    st = (ir.status or "").strip().lower()
    if st == "draft" and requested_phase != "request":
        return RedirectResponse(url=f"/integration/{req_id}/edit", status_code=302)

    display_phase = requested_phase
    hub_embedded = False
    hub_proposal_generating_override = False
    ws_out = None

    if requested_phase == "interview" and not view_summary:
        ws_out = serve_integration_interview_workspace(request, db, user, ir, background_tasks)
        db.refresh(ir)
        if ws_out.kind == "redirect":
            return RedirectResponse(url=ws_out.redirect_url or "/", status_code=302)
        if ws_out.kind == "generating":
            display_phase = "proposal"
            hub_proposal_generating_override = True
        elif ws_out.kind == "wizard" and ws_out.wizard_ctx:
            hub_embedded = True
            display_phase = "interview"
            ws_out.wizard_ctx["iv_submit_base"] = f"/integration/{req_id}"

    types_list = [t for t in (ir.impl_types or "").split(",") if t.strip()]
    program_groups = reference_code_program_groups_for_tabs(ir.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in program_groups)
    owner = None
    if privileged:
        owner = db.query(models.User).filter(models.User.id == ir.user_id).first()

    imsgs = sorted(list(ir.interview_messages or []), key=lambda m: (m.round_number, m.id))
    answered_sorted = [m for m in imsgs if m.is_answered]
    interview_summary_messages = _messages_to_list(answered_sorted)
    proposal_round_messages = interview_summary_messages

    hub_proposal_generating = hub_proposal_generating_override or (
        (ir.interview_status or "") == "generating_proposal"
    )

    proposal_html = ""
    if (ir.interview_status or "") == "completed" and (ir.proposal_text or "").strip():
        proposal_html = _markdown_to_html(wrap_unbracketed_agent_names(ir.proposal_text or ""))

    fs_stat = (getattr(ir, "fs_status", None) or "none").strip() or "none"
    dc_stat = (getattr(ir, "delivered_code_status", None) or "none").strip() or "none"
    fs_html = ""
    if fs_stat == "ready" and (getattr(ir, "fs_text", None) or "").strip():
        fs_html = _markdown_to_html(ir.fs_text)
    delivered_code_html = ""
    if dc_stat == "ready" and (getattr(ir, "delivered_code_text", None) or "").strip():
        delivered_code_html = _markdown_to_html(ir.delivered_code_text)

    fs_busy = fs_stat == "generating"
    dc_busy = dc_stat == "generating"
    gen_busy = fs_busy or dc_busy

    fs_body = (getattr(ir, "fs_text", None) or "").strip()
    can_operate_delivery = user_can_operate_delivery(user)
    can_start_delivered_code = bool(can_operate_delivery) and bool(fs_body) and (dc_stat != "generating")

    follow_msgs = sorted(
        list(ir.followup_messages or []),
        key=lambda m: (m.created_at or ir.created_at),
    )
    followup_turns = _pair_integration_followup_turns(follow_msgs)
    n_followup_user = sum(1 for m in follow_msgs if (m.role or "") == "user")
    chat_limit_reached = n_followup_user >= INT_CHAT_MAX_USER
    chat_error = (request.query_params.get("chat_err") or "").strip() or None
    delete_blocked = (request.query_params.get("delete_blocked") or "").strip()

    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "ir": ir,
        "rfp": ir,
        "iv_submit_base": f"/integration/{req_id}",
        "owner": owner,
        "delete_blocked_reason": delete_blocked,
        "hub_phase_open": display_phase,
        "hub_embedded": hub_embedded,
        "attachment_entries": _attachment_entries(ir),
        **_integration_impl_ui_ctx(db),
        "types_list": types_list,
        "source_program_groups": program_groups,
        "reference_section_count": ref_section_count,
        "interview_summary_messages": interview_summary_messages,
        "proposal_round_messages": proposal_round_messages,
        "hub_proposal_generating": hub_proposal_generating,
        "proposal_html": proposal_html,
        "fs_html": fs_html,
        "delivered_code_html": delivered_code_html,
        "fs_stat": fs_stat,
        "dc_stat": dc_stat,
        "fs_busy": fs_busy,
        "dc_busy": dc_busy,
        "gen_busy": gen_busy,
        "can_start_delivered_code": can_start_delivered_code,
        "can_operate_delivery": can_operate_delivery,
        "followup_turns": followup_turns,
        "chat_limit_reached": chat_limit_reached,
        "chat_error": chat_error,
        "max_followup_user_turns": INT_CHAT_MAX_USER,
        "hub_include_proposal_scripts": bool(proposal_html) and not hub_proposal_generating,
    }

    if hub_embedded and ws_out is not None and ws_out.kind == "wizard" and ws_out.wizard_ctx:
        ctx.update(ws_out.wizard_ctx)

    if hub_proposal_generating:
        ctx["rfp"] = SimpleNamespace(id=ir.id, title=ir.title or "")
        ctx["proposal_status_url"] = f"/integration/{ir.id}/proposal/status"
        ctx["proposal_done_redirect_url"] = integration_hub_url(ir.id, "proposal")

    return templates.TemplateResponse(request, "integration_unified_hub.html", ctx)


@router.post("/integration/{req_id}/chat")
def integration_chat_post(
    req_id: int,
    request: Request,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    from urllib.parse import quote

    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(
            models.IntegrationRequest.id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)

    st = (ir.status or "").strip().lower()
    chat_base = (
        f"/integration/{req_id}/edit"
        if st == "draft"
        else f"/integration/{req_id}?phase=request"
    )

    msg, verr = validate_integration_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote(verr)}#integration-followup-chat",
            status_code=303,
        )

    n_user = (
        db.query(models.IntegrationFollowupMessage)
        .filter(
            models.IntegrationFollowupMessage.request_id == ir.id,
            models.IntegrationFollowupMessage.role == "user",
        )
        .count()
    )
    if n_user >= INT_CHAT_MAX_USER:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote('후속 질문은 상한에 도달했습니다.')}#integration-followup-chat",
            status_code=303,
        )

    prior = (
        db.query(models.IntegrationFollowupMessage)
        .filter(models.IntegrationFollowupMessage.request_id == ir.id)
        .order_by(models.IntegrationFollowupMessage.created_at.asc())
        .all()
    )

    try:
        att_digest = build_attachment_llm_digest(_attachment_entries(ir), max_total_chars=10_000)
        reply = generate_integration_followup_reply(
            ir_summary=integration_request_llm_summary(ir, db),
            history_messages=prior,
            user_question=msg,
            attachment_digest=att_digest,
        )
    except Exception:
        reply = "응답을 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    db.add(
        models.IntegrationFollowupMessage(
            request_id=ir.id,
            role="user",
            content=msg,
        )
    )
    db.add(
        models.IntegrationFollowupMessage(
            request_id=ir.id,
            role="assistant",
            content=reply,
        )
    )
    db.commit()
    return RedirectResponse(url=f"{chat_base}#integration-followup-chat", status_code=303)


@router.post("/integration/{req_id}/improvement-proposal")
def integration_improvement_proposal_post(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """레거시 폼 호환: 이제 이 화면의 2. 인터뷰 이후 단계에서 제안서를 생성합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(
            models.IntegrationRequest.id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)


@router.get("/integration/{req_id}/attachment")
def integration_download_attachment(
    req_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not user.is_admin:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = q.first()
    if not ir:
        return RedirectResponse(url="/", status_code=302)
    entries = _attachment_entries(ir)
    if idx < 0 or idx >= len(entries):
        return RedirectResponse(url="/", status_code=302)
    ent = entries[idx]
    path = ent.get("path")
    fname = ent.get("filename") or "attachment"
    if not path:
        return RedirectResponse(url="/", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url="/", status_code=302)
        url = r2_storage.presigned_get_url(ref, fname)
        return RedirectResponse(url=url, status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(ref, filename=fname)


@router.patch("/integration/{req_id}/reference-codes")
async def patch_integration_reference_codes(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    ir = db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.id == req_id,
        models.IntegrationRequest.user_id == user.id,
    ).first()
    if not ir:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    try:
        body = await request.json()
        raw = json.dumps(body, ensure_ascii=False)
        norm = normalize_reference_code_payload(raw)
    except ValueError:
        return JSONResponse({"ok": False, "error": "too_large"}, status_code=400)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    ir.reference_code_payload = norm
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/integration/{req_id}/reference-codes")
def delete_integration_reference_codes(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    ir = db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.id == req_id,
        models.IntegrationRequest.user_id == user.id,
    ).first()
    if not ir:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    ir.reference_code_payload = None
    db.commit()
    return JSONResponse({"ok": True})
