import json
import mimetypes
import os
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from typing import List, Optional, Tuple, Any

from .. import models, auth, r2_storage, sap_fields
from ..paid_tier import user_can_access_fs_hub
from ..rfp_download_names import (
    content_disposition_attachment,
    delivered_abap_download_basename,
    fs_md_download_basename,
)
from ..rfp_reference_code import normalize_reference_code_payload, reference_code_program_groups_for_tabs
from ..rfp_phase_gates import rfp_for_owner_or_admin
from ..database import get_db
from ..templates_config import templates

router = APIRouter()

# 대시보드 연동 요청 배지용 (integration_router.IMPL_LABELS 와 동일)
INTEGRATION_IMPL_LABELS = {
    "excel_vba": "Excel / VBA 매크로",
    "python_script": "Python 스크립트",
    "small_webapp": "소규모 웹앱",
    "windows_batch": "Windows 배치 / 작업 스케줄러",
    "api_integration": "API·시스템 연동",
    "other": "기타",
}


def _ref_code_initial_from_rfp(rfp: Any) -> Optional[dict]:
    if not rfp:
        return None
    raw = getattr(rfp, "reference_code_payload", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

# Railway 웹 프로세스 로컬 디스크(ephemeral)·/tmp 는 재배포 시 사라질 수 있습니다.
# 첨부 바이너리는 Postgres에 넣지 않고, 여기 또는 R2(r2_storage)에 저장·DB에는 경로만 JSON 저장.
UPLOAD_DIR = (
    "/tmp/sap_uploads"
    if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
    else "uploads"
)
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_RFP_ATTACHMENTS = 5


async def _build_attachment_entries_from_uploads(
    user_id: int,
    uploads: List[UploadFile],
    notes: list[str],
) -> tuple[list[dict] | None, str | None]:
    """업로드 파일 목록을 저장하고 entries 생성. (None, err_key) 오류 시."""
    entries: list[dict] = []
    for i, up in enumerate(uploads):
        if not up.filename:
            continue
        if len(entries) >= MAX_RFP_ATTACHMENTS:
            return None, "too_many_attachments"
        ext = os.path.splitext(up.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None, "invalid_file"
        try:
            raw = await _read_upload_limited(up)
        except ValueError:
            return None, "file_too_large"
        if len(raw) == 0:
            return None, "empty_attachment"
        path, fname = _store_rfp_file(user_id, ext, raw, up.filename)
        note = (notes[i] if i < len(notes) else "") or ""
        entries.append({"path": path, "filename": fname, "note": note.strip()})
    return entries, None


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """멀티파트 업로드 본문을 읽습니다.

    일부 환경에서 비동기 read() 첫 호출만 빈 값이 되는 경우가 있어 seek(0) 후 단일 read() 시도,
    그래도 비면 동기 파일 객체에서 재시도합니다. (PostgreSQL에는 바이너리가 들어가지 않고 R2 또는 로컬 경로만 저장.)
    """

    async def _async_read_all() -> bytes:
        try:
            await upload.seek(0)
        except Exception:
            pass
        return await upload.read()

    raw = await _async_read_all()
    if len(raw) > MAX_FILE_SIZE_BYTES:
        raise ValueError("file_too_large")

    if not raw and getattr(upload, "file", None) is not None:
        def _sync_read_all() -> bytes:
            uf = upload.file
            try:
                uf.seek(0)
            except Exception:
                pass
            try:
                return uf.read() or b""
            except Exception:
                return b""

        raw = await run_in_threadpool(_sync_read_all)

    if len(raw) > MAX_FILE_SIZE_BYTES:
        raise ValueError("file_too_large")
    return raw


def _save_attachment_local(user_id: int, ext: str, data: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"rfp_{user_id}_{int(__import__('time').time())}{ext}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _store_rfp_file(user_id: int, ext: str, data: bytes, original_filename: str) -> Tuple[str, str]:
    """Persist bytes to R2 (if configured) or local UPLOAD_DIR; returns (file_path, file_name)."""
    ct = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    if r2_storage.is_configured():
        uri = r2_storage.upload_bytes(user_id, ext, data, ct)
        return uri, original_filename
    return _save_attachment_local(user_id, ext, data), original_filename


def _rfp_attachment_entries(rfp: models.RFP) -> list[dict]:
    """attachments_json 우선, 없으면 레거시 단일 file_path."""
    if getattr(rfp, "attachments_json", None):
        try:
            data = json.loads(rfp.attachments_json)
            if isinstance(data, list) and data:
                return [x for x in data if isinstance(x, dict) and x.get("path")]
        except Exception:
            pass
    if rfp.file_path:
        return [{
            "path": rfp.file_path,
            "filename": rfp.file_name or os.path.basename(rfp.file_path),
            "note": "",
        }]
    return []


def _set_rfp_attachments(rfp: models.RFP, entries: list[dict]) -> None:
    """레거시 file_path/file_name은 첫 번째 첨부와 동기화."""
    if not entries:
        rfp.attachments_json = None
        rfp.file_path = None
        rfp.file_name = None
        return
    rfp.attachments_json = json.dumps(entries, ensure_ascii=False)
    rfp.file_path = entries[0]["path"]
    rfp.file_name = entries[0]["filename"]


def _remove_stored_file(file_path: Optional[str]) -> None:
    if not file_path:
        return
    r2_storage.delete_if_r2_uri(file_path)
    if file_path.startswith(r2_storage.R2_PREFIX):
        return
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
    except OSError:
        pass


def _rfp_form_ctx(
    request: Request,
    user,
    modules,
    devtypes,
    writing_tip: str,
    error: str | None = None,
    form: dict | None = None,
    rfp=None,
    edit_mode: bool = False,
    attachment_entries: list | None = None,
):
    ctx = {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "writing_tip": writing_tip,
        "error": error,
        "form": form,
        "rfp": rfp,
        "edit_mode": edit_mode,
    }
    if attachment_entries is not None:
        ctx["attachment_entries"] = attachment_entries
    elif rfp is not None:
        ctx["attachment_entries"] = _rfp_attachment_entries(rfp)
    else:
        ctx["attachment_entries"] = []
    ctx["ref_code_initial"] = _ref_code_initial_from_rfp(rfp)
    return ctx


def _get_modules_devtypes(db: Session):
    modules = db.query(models.SAPModule).filter(models.SAPModule.is_active == True).order_by(models.SAPModule.sort_order).all()
    devtypes = db.query(models.DevType).filter(models.DevType.is_active == True).order_by(models.DevType.sort_order).all()
    return modules, devtypes


@router.get("/rfp/new", response_class=HTMLResponse)
def rfp_form(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""
    return templates.TemplateResponse(request, "rfp_form.html", {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "writing_tip": writing_tip,
        "attachment_entries": [],
        "ref_code_initial": None,
    })


@router.post("/rfp/new")
async def submit_rfp(
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    save_action: str = Form("submit"),
    reference_code_json: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    is_draft = (save_action.strip().lower() == "draft")
    notes_in = [note_0, note_1, note_2, note_3, note_4]

    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    def _form_dict():
        return {
            "program_id": program_id,
            "transaction_code": transaction_code,
            "title": title,
            "description": description,
            "sap_modules": sap_modules,
            "dev_types": dev_types,
            "notes": notes_in,
        }

    # 최대 3개 초과 검증
    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="max_selection",
                form=_form_dict(),
            ),
            status_code=400,
        )

    if not is_draft and (not sap_modules or not dev_types):
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="need_modules",
                form=_form_dict(),
            ),
            status_code=400,
        )

    pid, perr = sap_fields.validate_program_id(program_id, required=(not is_draft))
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error=err_key,
                form=_form_dict(),
            ),
            status_code=400,
        )

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error=err_key,
                form=_form_dict(),
            ),
            status_code=400,
        )

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="too_many_attachments",
                form=_form_dict(),
            ),
            status_code=400,
        )

    att_entries: list[dict] = []
    if n_uploads:
        att_entries, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                _rfp_form_ctx(
                    request, user, modules, devtypes, writing_tip,
                    error=err_a,
                    form=_form_dict(),
                ),
                status_code=400,
            )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="reference_code_too_large",
                form=_form_dict(),
            ),
            status_code=400,
        )

    rfp = models.RFP(
        user_id=user.id,
        program_id=pid,
        transaction_code=tc,
        title=title.strip(),
        sap_modules=",".join(sap_modules) if sap_modules else "",
        dev_types=",".join(dev_types) if dev_types else "",
        description=description,
        status="draft" if is_draft else "submitted",
        interview_status="pending",
        reference_code_payload=norm_ref,
    )
    _set_rfp_attachments(rfp, att_entries)
    db.add(rfp)
    db.commit()
    db.refresh(rfp)
    if is_draft:
        return RedirectResponse(url=f"/rfp/{rfp.id}/edit", status_code=302)
    return RedirectResponse(url=f"/rfp/{rfp.id}/success", status_code=302)


@router.get("/rfp/{rfp_id}/success", response_class=HTMLResponse)
def rfp_success(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "rfp_success.html", {"user": user, "rfp": rfp})


@router.get("/rfp/{rfp_id}/attachment")
def rfp_download_attachment(
    rfp_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
    if not user.is_admin:
        q = q.filter(models.RFP.user_id == user.id)
    rfp = q.first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    entries = _rfp_attachment_entries(rfp)
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


@router.get("/rfp/{rfp_id}/request", response_class=HTMLResponse)
def rfp_request_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """요청 정보 조회(+수정은 /rfp/:id/edit)."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "rfp_request_view.html",
        {
            "request": request,
            "user": user,
            "rfp": rfp,
            "attachment_entries": _rfp_attachment_entries(rfp),
        },
    )


@router.get("/rfp/{rfp_id}/dev-code", response_class=HTMLResponse)
def rfp_dev_code_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    groups = reference_code_program_groups_for_tabs(rfp.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in groups) if groups else 0
    if ref_section_count < 1:
        return RedirectResponse(url=f"/rfp/{rfp_id}/request", status_code=302)
    tabs_base_id = f"rfp-ref-src-{rfp.id}"
    return templates.TemplateResponse(
        request,
        "rfp_dev_code_view.html",
        {
            "request": request,
            "user": user,
            "rfp": rfp,
            "source_program_groups": groups,
            "reference_section_count": ref_section_count,
            "tabs_base_id": tabs_base_id,
        },
    )


@router.get("/rfp/{rfp_id}/fs", response_class=HTMLResponse)
def rfp_fs_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """유료 FS 조회 — 생성은 관리자 전용 POST."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(
        db,
        user=user,
        rfp_id=rfp_id,
        load_messages=False,
        load_fs_supplements=True,
    )
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return RedirectResponse(url=f"/rfp/{rfp_id}/proposal", status_code=302)
    from ..routers import interview_router as _ir

    fs_html = ""
    if (rfp.fs_status or "") == "ready" and (rfp.fs_text or "").strip():
        fs_html = _ir._markdown_to_html(rfp.fs_text)

    dc_html = ""
    if (
        (rfp.delivered_code_status or "") == "ready"
        and (rfp.delivered_code_text or "").strip()
    ):
        dc_html = _ir._markdown_to_html(rfp.delivered_code_text)

    return templates.TemplateResponse(
        request,
        "rfp_fs_view.html",
        {
            "request": request,
            "user": user,
            "rfp": rfp,
            "fs_html": fs_html,
            "delivered_code_html": dc_html,
        },
    )


@router.get("/rfp/{rfp_id}/paid-generation-status")
def rfp_paid_generation_status(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """FS·납품 코드 생성 진행 여부 폴링(회원·관리자)."""
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return JSONResponse(
        {
            "fs_status": getattr(rfp, "fs_status", None) or "none",
            "delivered_code_status": getattr(rfp, "delivered_code_status", None) or "none",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/rfp/{rfp_id}/fs/download")
def rfp_fs_download(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return RedirectResponse(url="/", status_code=302)
    if (rfp.fs_status or "") != "ready" or not (rfp.fs_text or "").strip():
        return RedirectResponse(url=f"/rfp/{rfp_id}/fs", status_code=302)
    body = (rfp.fs_text or "").encode("utf-8")
    fname = fs_md_download_basename(getattr(rfp, "program_id", None), getattr(rfp, "title", None))
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )


@router.get("/rfp/{rfp_id}/delivered-code/download")
def rfp_delivered_code_download(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return RedirectResponse(url="/", status_code=302)
    if (
        (rfp.delivered_code_status or "") != "ready"
        or not (rfp.delivered_code_text or "").strip()
    ):
        return RedirectResponse(url=f"/rfp/{rfp_id}/fs", status_code=302)
    body = (rfp.delivered_code_text or "").encode("utf-8")
    fname = delivered_abap_download_basename(getattr(rfp, "program_id", None), getattr(rfp, "title", None))
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )


@router.get("/rfp/{rfp_id}/edit", response_class=HTMLResponse)
def rfp_edit_form(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""
    return templates.TemplateResponse(request, "rfp_form.html", {
        "request": request, "user": user, "rfp": rfp,
        "modules": modules, "devtypes": devtypes, "writing_tip": writing_tip,
        "edit_mode": True,
        "attachment_entries": _rfp_attachment_entries(rfp),
        "ref_code_initial": _ref_code_initial_from_rfp(rfp),
    })


@router.post("/rfp/{rfp_id}/edit")
async def rfp_edit_submit(
    rfp_id: int,
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
    description: str = Form(""),
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
    reference_code_json: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    is_draft = (save_action.strip().lower() == "draft")
    if rfp.status != "draft":
        is_draft = False

    notes_in = [note_0, note_1, note_2, note_3, note_4]
    notes_orig = [note_orig_0, note_orig_1, note_orig_2, note_orig_3, note_orig_4]
    del_flags = [bool(delete_0), bool(delete_1), bool(delete_2), bool(delete_3), bool(delete_4)]

    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    def _form_dict():
        return {
            "program_id": program_id,
            "transaction_code": transaction_code,
            "title": title,
            "description": description,
            "sap_modules": sap_modules,
            "dev_types": dev_types,
            "notes": notes_in,
        }

    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="max_selection",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    if not is_draft and (not sap_modules or not dev_types):
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="need_modules",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    pid, perr = sap_fields.validate_program_id(program_id, required=(not is_draft))
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error=err_key,
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error=err_key,
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    existing = _rfp_attachment_entries(rfp)
    kept: list[dict] = []
    for i, att in enumerate(existing):
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
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="too_many_attachments",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    new_parts: list[dict] = []
    if n_uploads:
        new_parts, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                _rfp_form_ctx(
                    request, user, modules, devtypes, writing_tip,
                    error=err_a,
                    form=_form_dict(),
                    rfp=rfp,
                    edit_mode=True,
                ),
                status_code=400,
            )

    remaining = MAX_RFP_ATTACHMENTS - len(kept)
    if len(new_parts) > remaining:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="too_many_attachments",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    combined = kept + new_parts

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip,
                error="reference_code_too_large",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    rfp.program_id = pid
    rfp.transaction_code = tc
    rfp.title = title.strip()
    rfp.sap_modules = ",".join(sap_modules) if sap_modules else ""
    rfp.dev_types = ",".join(dev_types) if dev_types else ""
    rfp.description = description
    rfp.reference_code_payload = norm_ref
    if is_draft:
        rfp.status = "draft"
    else:
        rfp.status = "submitted"

    _set_rfp_attachments(rfp, combined)
    db.commit()
    if is_draft:
        return RedirectResponse(url=f"/rfp/{rfp_id}/edit", status_code=302)
    return RedirectResponse(url="/", status_code=302)


@router.patch("/rfp/{rfp_id}/reference-codes")
async def patch_rfp_reference_codes(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """편집 중 참고 ABAP JSON 자동 저장 (본 RFP 행만)."""
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    try:
        raw = json.dumps(body, ensure_ascii=False)
        norm = normalize_reference_code_payload(raw)
    except ValueError:
        return JSONResponse({"ok": False, "error": "too_large"}, status_code=400)
    rfp.reference_code_payload = norm
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/rfp/{rfp_id}/reference-codes")
def delete_rfp_reference_codes(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    rfp.reference_code_payload = None
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_legacy_redirect(request: Request):
    """레거시 URL — 홈으로 리다이렉트(진행 건수는 홈 타일)."""
    return RedirectResponse(url="/", status_code=302)
