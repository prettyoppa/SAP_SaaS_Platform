import mimetypes
import os
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Tuple

from .. import models, auth, r2_storage
from ..database import get_db
from ..templates_config import templates

router = APIRouter()

# Railway 등에서는 상대 경로 uploads 쓰기 실패할 수 있어 /tmp 사용
UPLOAD_DIR = (
    "/tmp/sap_uploads"
    if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
    else "uploads"
)
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


async def _read_upload_limited(upload: UploadFile) -> bytes:
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE_BYTES:
            raise ValueError("file_too_large")
    return b"".join(chunks)


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
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    # 최대 3개 초과 검증
    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            {"user": user, "modules": modules, "devtypes": devtypes,
             "writing_tip": writing_tip, "error": "max_selection"},
            status_code=400,
        )

    file_path = None
    file_name = None
    if attachment and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                {"user": user, "modules": modules, "devtypes": devtypes,
                 "writing_tip": writing_tip, "error": "invalid_file"},
                status_code=400,
            )
        try:
            raw = await _read_upload_limited(attachment)
        except ValueError:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                {"user": user, "modules": modules, "devtypes": devtypes,
                 "writing_tip": writing_tip, "error": "file_too_large"},
                status_code=400,
            )
        if len(raw) == 0:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                {"user": user, "modules": modules, "devtypes": devtypes,
                 "writing_tip": writing_tip, "error": "empty_attachment"},
                status_code=400,
            )
        file_path, file_name = _store_rfp_file(user.id, ext, raw, attachment.filename)

    rfp = models.RFP(
        user_id=user.id,
        program_id=program_id.strip().upper() if program_id else None,
        transaction_code=transaction_code.strip().upper() if transaction_code else None,
        title=title,
        sap_modules=",".join(sap_modules),
        dev_types=",".join(dev_types),
        description=description,
        file_path=file_path,
        file_name=file_name,
        status="submitted",
    )
    db.add(rfp)
    db.commit()
    db.refresh(rfp)
    return RedirectResponse(url=f"/rfp/{rfp.id}/success", status_code=302)


@router.get("/rfp/{rfp_id}/success", response_class=HTMLResponse)
def rfp_success(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "rfp_success.html", {"user": user, "rfp": rfp})


@router.get("/rfp/{rfp_id}/attachment")
def rfp_download_attachment(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
    if not user.is_admin:
        q = q.filter(models.RFP.user_id == user.id)
    rfp = q.first()
    if not rfp or not rfp.file_path:
        return RedirectResponse(url="/dashboard", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(rfp.file_path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url="/dashboard", status_code=302)
        url = r2_storage.presigned_get_url(ref, rfp.file_name or "attachment")
        return RedirectResponse(url=url, status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url="/dashboard", status_code=302)
    return FileResponse(ref, filename=rfp.file_name or os.path.basename(ref))


@router.get("/rfp/{rfp_id}/edit", response_class=HTMLResponse)
def rfp_edit_form(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""
    return templates.TemplateResponse(request, "rfp_form.html", {
        "request": request, "user": user, "rfp": rfp,
        "modules": modules, "devtypes": devtypes, "writing_tip": writing_tip,
        "edit_mode": True,
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
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/dashboard", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)

    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            {"user": user, "rfp": rfp, "modules": modules,
             "devtypes": devtypes, "error": "max_selection", "edit_mode": True},
            status_code=400,
        )

    rfp.program_id = program_id.strip().upper() if program_id else rfp.program_id
    rfp.transaction_code = transaction_code.strip().upper() if transaction_code else rfp.transaction_code
    rfp.title = title
    rfp.sap_modules = ",".join(sap_modules)
    rfp.dev_types = ",".join(dev_types)
    rfp.description = description

    if attachment and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext in ALLOWED_EXTENSIONS:
            try:
                raw = await _read_upload_limited(attachment)
            except ValueError:
                writing_tip_setting = db.query(models.SiteSettings).filter(
                    models.SiteSettings.key == "rfp_writing_tip"
                ).first()
                writing_tip = writing_tip_setting.value if writing_tip_setting else ""
                return templates.TemplateResponse(
                    request,
                    "rfp_form.html",
                    {"user": user, "rfp": rfp, "modules": modules, "devtypes": devtypes,
                     "writing_tip": writing_tip, "error": "file_too_large", "edit_mode": True},
                    status_code=400,
                )
            if len(raw) == 0:
                writing_tip_setting = db.query(models.SiteSettings).filter(
                    models.SiteSettings.key == "rfp_writing_tip"
                ).first()
                writing_tip = writing_tip_setting.value if writing_tip_setting else ""
                return templates.TemplateResponse(
                    request,
                    "rfp_form.html",
                    {"user": user, "rfp": rfp, "modules": modules, "devtypes": devtypes,
                     "writing_tip": writing_tip, "error": "empty_attachment", "edit_mode": True},
                    status_code=400,
                )
            _remove_stored_file(rfp.file_path)
            rfp.file_path, rfp.file_name = _store_rfp_file(user.id, ext, raw, attachment.filename)

    db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_by: str = "newest",
    db: Session = Depends(get_db),
):
    from datetime import datetime as _dt
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(models.RFP)
    if not user.is_admin:
        query = query.filter(models.RFP.user_id == user.id)

    all_rfps = query.order_by(models.RFP.created_at.desc()).all()

    # 상태별 카운트 (필터 전)
    total = len(all_rfps)
    completed = sum(1 for r in all_rfps if r.interview_status == "completed")
    in_review = sum(1 for r in all_rfps if r.interview_status == "in_progress")
    submitted = sum(1 for r in all_rfps if r.interview_status == "pending" and r.status == "submitted")

    # 상태 필터
    if status_filter == "completed":
        rfps = [r for r in all_rfps if r.interview_status == "completed"]
    elif status_filter == "in_review":
        rfps = [r for r in all_rfps if r.interview_status == "in_progress"]
    elif status_filter == "submitted":
        rfps = [r for r in all_rfps if r.interview_status == "pending" and r.status == "submitted"]
    else:
        rfps = all_rfps

    # 날짜 범위 필터
    try:
        dt_from = _dt.strptime(date_from, "%Y-%m-%d") if date_from else None
    except ValueError:
        dt_from = None
    try:
        dt_to_parsed = _dt.strptime(date_to, "%Y-%m-%d") if date_to else None
        if dt_to_parsed:
            dt_to_parsed = dt_to_parsed.replace(hour=23, minute=59, second=59)
    except ValueError:
        dt_to_parsed = None

    if dt_from:
        rfps = [r for r in rfps if r.created_at >= dt_from]
    if dt_to_parsed:
        rfps = [r for r in rfps if r.created_at <= dt_to_parsed]

    # 정렬
    if sort_by == "oldest":
        rfps = sorted(rfps, key=lambda r: r.created_at)
    elif sort_by == "status":
        order = {"completed": 0, "in_progress": 1, "generating_proposal": 2, "pending": 3}
        rfps = sorted(rfps, key=lambda r: order.get(r.interview_status, 9))
    else:  # newest (default)
        rfps = sorted(rfps, key=lambda r: r.created_at, reverse=True)

    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "user": user,
        "rfps": rfps,
        "status_filter": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "sort_by": sort_by,
        "counts": {"total": total, "completed": completed, "in_review": in_review, "submitted": submitted},
    })
