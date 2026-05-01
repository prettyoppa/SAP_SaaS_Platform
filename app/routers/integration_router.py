"""SAP 연동 개발 요청 라우터 (VBA, Python, 배치, API 등)."""
from __future__ import annotations

import json
import os
from typing import List

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
from ..templates_config import templates
from ..workflow_rfp_bridge import create_workflow_rfp_from_integration
from ..integration_followup_chat import (
    generate_integration_followup_reply,
    integration_request_llm_summary,
    validate_integration_user_message,
)
from ..routers.interview_router import _markdown_to_html, _run_proposal_background
from .rfp_router import (
    MAX_RFP_ATTACHMENTS,
    _build_attachment_entries_from_uploads,
    _get_modules_devtypes,
    r2_storage,
)

router = APIRouter()

IMPL_LABELS = {
    "excel_vba": "Excel / VBA 매크로",
    "python_script": "Python 스크립트",
    "small_webapp": "소규모 웹앱",
    "windows_batch": "Windows 배치 / 작업 스케줄러",
    "api_integration": "API·시스템 연동",
    "other": "기타",
}

MIN_IMPROVEMENT_PROPOSAL_LEN = 20


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

    is_admin = bool(user and user.is_admin)

    rfp_total_rows = 0
    rfp_landing_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    svc_abap_tile_links: dict[str, str] = {}
    rfps_filtered: list = []

    show_rfp_owner = False
    if user:
        admin_view = is_admin
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

    is_admin = bool(user and user.is_admin)
    menu_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    menu_total_rows = 0
    menu_tile_links: dict[str, str] = {}
    filtered_rows: list[models.IntegrationRequest] = []
    show_request_owner = bool(user and is_admin)

    if user:
        admin_view = is_admin
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
            "impl_labels": IMPL_LABELS,
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
            "impl_labels": IMPL_LABELS,
            "error": None,
            "form": None,
        },
    )


@router.post("/integration/new")
async def integration_new_submit(
    request: Request,
    title: str = Form(...),
    impl_types: List[str] = Form(default=[]),
    sap_touchpoints: str = Form(""),
    environment_notes: str = Form(""),
    security_notes: str = Form(""),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    reference_code_json: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    notes_in = [note_0, note_1, note_2, note_3, note_4]

    def _form_dict():
        return {
            "title": title,
            "impl_types": impl_types,
            "sap_touchpoints": sap_touchpoints,
            "environment_notes": environment_notes,
            "security_notes": security_notes,
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
                "impl_labels": IMPL_LABELS,
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
                    "impl_labels": IMPL_LABELS,
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
                "impl_labels": IMPL_LABELS,
                "error": "reference_code_too_large",
                "form": _form_dict(),
            },
            status_code=400,
        )

    impl_clean = [x for x in impl_types if x in IMPL_LABELS]
    if not impl_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                "impl_labels": IMPL_LABELS,
                "error": "need_impl_types",
                "form": _form_dict(),
            },
            status_code=400,
        )
    ir = models.IntegrationRequest(
        user_id=user.id,
        title=title.strip(),
        impl_types=",".join(impl_clean) if impl_clean else "",
        sap_touchpoints=sap_touchpoints.strip() or None,
        environment_notes=environment_notes.strip() or None,
        security_notes=security_notes.strip() or None,
        description=description.strip() or None,
        reference_code_payload=norm_ref,
        status="submitted",
        interview_status="pending",
    )
    _set_attachments(ir, att_entries)
    db.add(ir)
    db.commit()
    db.refresh(ir)
    return RedirectResponse(url=f"/integration/{ir.id}", status_code=302)


@router.get("/integration/{req_id}", response_class=HTMLResponse)
def integration_detail(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not user.is_admin:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = (
        q.options(
            joinedload(models.IntegrationRequest.followup_messages),
            joinedload(models.IntegrationRequest.workflow_rfp).joinedload(models.RFP.messages),
        ).first()
    )
    if not ir:
        return RedirectResponse(url="/", status_code=302)
    types_list = [t for t in (ir.impl_types or "").split(",") if t.strip()]
    program_groups = reference_code_program_groups_for_tabs(ir.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in program_groups)
    owner = None
    if user.is_admin:
        owner = db.query(models.User).filter(models.User.id == ir.user_id).first()

    follow_msgs = sorted(
        list(ir.followup_messages or []),
        key=lambda m: (m.created_at or ir.created_at),
    )
    followup_turns = _pair_integration_followup_turns(follow_msgs)
    n_followup_user = sum(1 for m in follow_msgs if (m.role or "") == "user")
    chat_limit_reached = n_followup_user >= INT_CHAT_MAX_USER
    chat_error = (request.query_params.get("chat_err") or "").strip() or None
    wf_err = (request.query_params.get("wf_err") or "").strip() or None

    return templates.TemplateResponse(
        request,
        "integration_detail.html",
        {
            "request": request,
            "user": user,
            "ir": ir,
            "owner": owner,
            "attachment_entries": _attachment_entries(ir),
            "impl_labels": IMPL_LABELS,
            "types_list": types_list,
            "source_program_groups": program_groups,
            "reference_section_count": ref_section_count,
            "followup_turns": followup_turns,
            "chat_limit_reached": chat_limit_reached,
            "chat_error": chat_error,
            "wf_err": wf_err,
            "max_followup_user_turns": INT_CHAT_MAX_USER,
        },
    )


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

    msg, verr = validate_integration_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"/integration/{req_id}?chat_err={quote(verr)}#integration-interview-block",
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
            url=f"/integration/{req_id}?chat_err={quote('후속 질문은 상한에 도달했습니다.')}"
            f"#integration-interview-block",
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
            ir_summary=integration_request_llm_summary(ir),
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
    return RedirectResponse(url=f"/integration/{req_id}#integration-interview-block", status_code=303)


@router.post("/integration/{req_id}/improvement-proposal")
def integration_improvement_proposal_post(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    improvement_request_text: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.followup_messages))
        .filter(
            models.IntegrationRequest.id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    if getattr(ir, "workflow_rfp_id", None):
        return RedirectResponse(url=f"/integration/{req_id}?wf_err=already", status_code=302)
    txt = (improvement_request_text or "").strip()
    if len(txt) < MIN_IMPROVEMENT_PROPOSAL_LEN:
        return RedirectResponse(url=f"/integration/{req_id}?wf_err=short", status_code=302)

    fmsgs = sorted(
        list(ir.followup_messages or []),
        key=lambda m: (m.created_at or ir.created_at),
    )
    rfp = create_workflow_rfp_from_integration(
        db,
        ir=ir,
        improvement_text=txt,
        owner_user_id=user.id,
        followup_messages=fmsgs,
    )
    background_tasks.add_task(_run_proposal_background, rfp.id)
    return RedirectResponse(url=f"/rfp/{rfp.id}/proposal/generating", status_code=302)


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
