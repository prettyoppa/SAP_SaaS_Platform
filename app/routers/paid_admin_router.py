"""관리자: 유료 RFP 배송(FS·납품 코드) — 생성 트리거 전용."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
import os

from .. import auth, models, r2_storage
from ..database import get_db
from ..paid_generation import (
    resolved_fs_markdown_for_codegen,
    run_delivered_code_job,
    run_fs_generation_job,
)
from ..paid_tier import paid_engagement_is_active
from ..templates_config import templates
from ..routers.interview_router import _messages_to_list
from ..routers.rfp_router import _read_upload_limited, _store_rfp_file, UPLOAD_DIR

router = APIRouter(prefix="/admin", tags=["admin-delivery"])


def _require_admin(request: Request, db: Session):
    user = auth.get_current_user(request, db)
    if not user or not user.is_admin:
        return None
    return user


@router.get("/rfp/{rfp_id}/delivery", response_class=HTMLResponse)
def admin_rfp_delivery_page(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    err: str | None = None,
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)

    rfp = (
        db.query(models.RFP)
        .options(
            joinedload(models.RFP.messages),
            joinedload(models.RFP.owner),
            joinedload(models.RFP.fs_supplements),
        )
        .filter(models.RFP.id == rfp_id)
        .first()
    )
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)

    msgs = sorted(_messages_to_list(rfp.messages), key=lambda x: (x["round_number"], x["id"]))
    fs_body, fs_src_err = resolved_fs_markdown_for_codegen(db, rfp)
    can_start_code = bool(fs_body and fs_body.strip()) and (rfp.delivered_code_status or "") != "generating"

    return templates.TemplateResponse(
        request,
        "admin/rfp_delivery.html",
        {
            "request": request,
            "user": actor,
            "rfp": rfp,
            "messages": msgs,
            "paid_engagement_active": paid_engagement_is_active(rfp),
            "delivery_err": err,
            "can_start_delivered_code": can_start_code,
            "fs_codegen_preview_error": fs_src_err,
            "admin_upload_dir_hint": UPLOAD_DIR,
            "fs_stores_r2": r2_storage.is_configured(),
            "job_log_poll_ms": 2500,
        },
    )


@router.get("/rfp/{rfp_id}/delivery/generation-log")
def admin_delivery_generation_log_json(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _require_admin(request, db)
    if not actor:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse(
        {
            "fs_status": getattr(rfp, "fs_status", None) or "none",
            "delivered_code_status": getattr(rfp, "delivered_code_status", None) or "none",
            "fs_job_log": getattr(rfp, "fs_job_log", None) or "",
            "delivered_job_log": getattr(rfp, "delivered_job_log", None) or "",
            "fs_error": getattr(rfp, "fs_error", None) or "",
            "delivered_code_error": getattr(rfp, "delivered_code_error", None) or "",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/rfp/{rfp_id}/delivery/fs-start")
def admin_start_fs_generation(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    if (rfp.fs_status or "") == "generating":
        return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
    rfp.fs_status = "generating"
    rfp.fs_error = None
    rfp.fs_job_log = None
    db.commit()
    background_tasks.add_task(run_fs_generation_job, rfp_id)
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)


@router.post("/rfp/{rfp_id}/delivery/code-start")
def admin_start_delivered_code(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    fs_body, fs_err = resolved_fs_markdown_for_codegen(db, rfp)
    if fs_err or not (fs_body or "").strip():
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_not_ready",
            status_code=302,
        )
    if (rfp.delivered_code_status or "") == "generating":
        return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
    rfp.delivered_code_status = "generating"
    rfp.delivered_code_error = None
    rfp.delivered_job_log = None
    db.commit()
    background_tasks.add_task(run_delivered_code_job, rfp_id)
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)


@router.post("/rfp/{rfp_id}/delivery/fs-codegen-source")
def admin_set_fs_codegen_source(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    fs_codegen_source: str = Form("agent"),
):
    """ABAP 코드 생성에 사용할 FS: 에이전트(fs_text) 또는 업로드한 보조 .md 중 하나."""
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    src = (fs_codegen_source or "agent").strip()
    if src == "agent":
        rfp.fs_codegen_supplement_id = None
    else:
        try:
            sid = int(src)
        except ValueError:
            return RedirectResponse(
                url=f"/admin/rfp/{rfp_id}/delivery?err=fs_codegen_source_bad",
                status_code=302,
            )
        ok = (
            db.query(models.RfpFsSupplement)
            .filter(models.RfpFsSupplement.id == sid, models.RfpFsSupplement.rfp_id == rfp.id)
            .first()
        )
        if not ok:
            return RedirectResponse(
                url=f"/admin/rfp/{rfp_id}/delivery?err=fs_codegen_source_bad",
                status_code=302,
            )
        rfp.fs_codegen_supplement_id = sid
    db.commit()
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)


@router.post("/rfp/{rfp_id}/delivery/fs-supplement-upload")
async def admin_upload_fs_supplement(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    if not file.filename:
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_upload_no_name",
            status_code=302,
        )
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".md":
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_bad_ext",
            status_code=302,
        )
    try:
        raw = await _read_upload_limited(file)
    except ValueError:
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_too_large",
            status_code=302,
        )
    if not raw:
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_upload_empty",
            status_code=302,
        )
    uid_store = int(rfp.user_id) if rfp.user_id else actor.id
    path_stored, fname_stored = _store_rfp_file(uid_store, ext, raw, file.filename or "fs.md")
    sup = models.RfpFsSupplement(
        rfp_id=rfp.id,
        stored_path=path_stored,
        filename=fname_stored,
        uploaded_by_user_id=actor.id,
    )
    db.add(sup)
    db.commit()
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)


def _delete_supplement_blob(stored_path: str) -> None:
    r2_storage.delete_if_r2_uri(stored_path)
    if (stored_path or "").startswith("r2://"):
        return
    try:
        if stored_path and os.path.isfile(stored_path):
            os.remove(stored_path)
    except OSError:
        pass


@router.post("/rfp/{rfp_id}/delivery/fs-supplement/{supplement_id}/delete")
def admin_delete_fs_supplement(
    rfp_id: int,
    supplement_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    sup = (
        db.query(models.RfpFsSupplement)
        .filter(models.RfpFsSupplement.id == supplement_id, models.RfpFsSupplement.rfp_id == rfp.id)
        .first()
    )
    if not sup:
        return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
    if rfp.fs_codegen_supplement_id == sup.id:
        rfp.fs_codegen_supplement_id = None
    p = sup.stored_path
    db.delete(sup)
    db.commit()
    _delete_supplement_blob(p or "")
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
