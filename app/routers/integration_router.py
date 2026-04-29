"""SAP 연동 개발 요청 라우터 (VBA, Python, 배치, API 등)."""
from __future__ import annotations

import json
import os
from typing import List

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..rfp_reference_code import normalize_reference_code_payload, reference_code_program_groups_for_tabs
from ..rfp_landing import (
    BUCKET_ORDER,
    DEFAULT_SERVICE_ABAP_INTRO_MD_KO,
    user_rfp_landing_data,
)
from ..templates_config import templates
from ..routers.interview_router import _markdown_to_html
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

    rfp_landing_counts = {k: 0 for k in BUCKET_ORDER}
    rfp_landing_buckets = {k: [] for k in BUCKET_ORDER}
    if user:
        rfp_landing_counts, rfp_landing_buckets = user_rfp_landing_data(db, user.id)

    bucket_meta = {
        "delivery": {
            "label": "납품",
            "icon": "fa-truck",
            "fg": "#94a3b8",
            "bg": "rgba(148,163,184,.22)",
            "hint": "FS·최종 코드 납품(추후)",
        },
        "proposal": {"label": "제안", "icon": "fa-file-lines", "fg": "#22c55e", "bg": "rgba(34,197,94,.18)"},
        "analysis": {"label": "분석", "icon": "fa-magnifying-glass-chart", "fg": "#6366f1", "bg": "rgba(99,102,241,.18)"},
        "in_progress": {"label": "진행중", "icon": "fa-spinner", "fg": "#eab308", "bg": "rgba(234,179,8,.2)"},
        "draft": {"label": "임시저장", "icon": "fa-floppy-disk", "fg": "#64748b", "bg": "rgba(100,116,139,.2)"},
    }
    return templates.TemplateResponse(
        request,
        "services_abap.html",
        {
            "request": request,
            "user": user,
            "service_abap_intro_html": intro_html,
            "rfp_landing_counts": rfp_landing_counts,
            "rfp_landing_buckets": rfp_landing_buckets,
            "rfp_bucket_order": list(BUCKET_ORDER),
            "bucket_meta": bucket_meta,
        },
    )


@router.get("/integration", response_class=HTMLResponse)
def integration_landing(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    mine: list[models.IntegrationRequest] = []
    if user:
        mine = (
            db.query(models.IntegrationRequest)
            .filter(models.IntegrationRequest.user_id == user.id)
            .order_by(models.IntegrationRequest.created_at.desc())
            .limit(20)
            .all()
        )
    return templates.TemplateResponse(
        request,
        "integration_landing.html",
        {"request": request, "user": user, "mine": mine},
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
    ir = db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.id == req_id
    ).first()
    if not ir or (ir.user_id != user.id and not user.is_admin):
        return RedirectResponse(url="/", status_code=302)
    types_list = [t for t in (ir.impl_types or "").split(",") if t.strip()]
    program_groups = reference_code_program_groups_for_tabs(ir.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in program_groups)
    return templates.TemplateResponse(
        request,
        "integration_detail.html",
        {
            "request": request,
            "user": user,
            "ir": ir,
            "attachment_entries": _attachment_entries(ir),
            "impl_labels": IMPL_LABELS,
            "types_list": types_list,
            "source_program_groups": program_groups,
            "reference_section_count": ref_section_count,
        },
    )


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
