"""관리자: 유료 RFP 배송(FS·납품 코드) — 생성 트리거 전용."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
import os

from .. import auth, models, r2_storage
from ..delivered_code_package import rfp_delivered_body_ready
from ..abap_analysis_generation import (
    resolved_abap_analysis_fs_for_codegen,
    run_abap_analysis_delivered_code_job,
    run_abap_analysis_fs_job,
)
from ..database import get_db
from ..paid_generation import (
    resolved_fs_markdown_for_codegen,
    run_delivered_code_job,
    run_fs_generation_job,
)
from ..integration_generation import (
    append_integration_job_log,
    integration_deliverable_job_stale,
    run_integration_deliverable_job,
    run_integration_fs_job,
)
from ..paid_tier import user_can_operate_delivery
from ..templates_config import templates
from ..rfp_phase_gates import rfp_phase_gates
from ..routers.rfp_router import _read_upload_limited, _store_rfp_file

router = APIRouter(prefix="/admin", tags=["admin-delivery"])


def _require_delivery_operator(request: Request, db: Session):
    user = auth.get_current_user(request, db)
    if not user or not user_can_operate_delivery(user):
        return None
    return user


@router.get("/rfp/{rfp_id}/delivery", response_class=HTMLResponse)
def admin_rfp_delivery_page(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    err: str | None = None,
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)

    rfp = (
        db.query(models.RFP)
        .options(
            joinedload(models.RFP.owner),
            joinedload(models.RFP.fs_supplements),
        )
        .filter(models.RFP.id == rfp_id)
        .first()
    )
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)

    fs_body, fs_src_err = resolved_fs_markdown_for_codegen(db, rfp)
    can_start_code = bool(fs_body and fs_body.strip()) and (rfp.delivered_code_status or "").strip() != "generating"

    fs_busy = (rfp.fs_status or "").strip() == "generating"
    dc_busy = (rfp.delivered_code_status or "").strip() == "generating"
    gen_busy = fs_busy or dc_busy
    sups = getattr(rfp, "fs_supplements", None) or []
    has_fs_material = bool(
        ((rfp.fs_status or "").strip() == "ready" and (rfp.fs_text or "").strip()) or len(sups) > 0
    )
    has_code_material = rfp_delivered_body_ready(rfp)

    ph = rfp_phase_gates(rfp, actor)
    dev_code_view_href = ph.get("dev_code_href")
    has_dev_code_nav = bool(ph.get("has_dev_code"))

    return templates.TemplateResponse(
        request,
        "admin/rfp_delivery.html",
        {
            "request": request,
            "user": actor,
            "rfp": rfp,
            "delivery_err": err,
            "can_start_delivered_code": can_start_code,
            "fs_codegen_preview_error": fs_src_err,
            "job_log_poll_ms": 2500,
            "fs_busy": fs_busy,
            "dc_busy": dc_busy,
            "gen_busy": gen_busy,
            "has_fs_material": has_fs_material,
            "has_code_material": has_code_material,
            "dev_code_view_href": dev_code_view_href,
            "has_dev_code_nav": has_dev_code_nav,
        },
    )


@router.get("/rfp/{rfp_id}/delivery/generation-log")
def admin_delivery_generation_log_json(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
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
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    if (rfp.fs_status or "").strip() == "generating":
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
    actor = _require_delivery_operator(request, db)
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
    if (rfp.delivered_code_status or "").strip() == "generating":
        return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
    rfp.delivered_code_status = "generating"
    rfp.delivered_code_error = None
    rfp.delivered_job_log = None
    db.commit()
    background_tasks.add_task(run_delivered_code_job, rfp_id)
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)


@router.post("/rfp/{rfp_id}/delivery/fs-supplement-upload")
async def admin_upload_fs_supplement(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(...),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)
    uid_store = int(rfp.user_id) if rfp.user_id else actor.id
    upload_list = files if isinstance(files, list) else [files]
    if not upload_list:
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_upload_no_name",
            status_code=302,
        )
    pending: list[tuple[bytes, str]] = []
    for file in upload_list:
        if not file.filename:
            continue
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
        if raw:
            pending.append((raw, file.filename or "fs.md"))
    if not pending:
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_upload_empty",
            status_code=302,
        )
    for raw, fname in pending:
        path_stored, fname_stored = _store_rfp_file(uid_store, ".md", raw, fname)
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
    actor = _require_delivery_operator(request, db)
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


@router.post("/integration/{req_id}/delivery/fs-start")
def admin_integration_fs_start(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id).first()
    if not ir:
        return RedirectResponse(url="/admin", status_code=302)
    if (ir.fs_status or "").strip() == "generating":
        return RedirectResponse(url=f"/integration/{req_id}?phase=fs", status_code=302)
    ir.fs_status = "generating"
    ir.fs_error = None
    ir.fs_job_log = None
    db.commit()
    background_tasks.add_task(run_integration_fs_job, req_id)
    return RedirectResponse(url=f"/integration/{req_id}?phase=fs", status_code=302)


@router.post("/integration/{req_id}/delivery/code-start")
def admin_integration_code_start(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id).first()
    if not ir:
        return RedirectResponse(url="/admin", status_code=302)
    fs_body = (ir.fs_text or "").strip()
    if not fs_body or (ir.fs_status or "").strip() != "ready":
        return RedirectResponse(url=f"/integration/{req_id}?phase=fs&err=fs_not_ready", status_code=302)
    dc_generating = (ir.delivered_code_status or "").strip() == "generating"
    if dc_generating and not integration_deliverable_job_stale(ir, minutes=8):
        return RedirectResponse(url=f"/integration/{req_id}?phase=devcode", status_code=302)
    if dc_generating and integration_deliverable_job_stale(ir, minutes=8):
        append_integration_job_log(req_id, "delivered_job_log", "이전 generating 무응답 — 작업 재시작")
    elif not dc_generating:
        ir.delivered_job_log = None
    ir.delivered_code_status = "generating"
    ir.delivered_code_error = None
    db.commit()
    background_tasks.add_task(run_integration_deliverable_job, req_id)
    return RedirectResponse(url=f"/integration/{req_id}?phase=devcode", status_code=302)


@router.post("/integration/{req_id}/delivery/code-cancel")
def admin_integration_code_cancel(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """generating 고착 시 운영자가 수동으로 중단하고 재시도할 수 있게 한다."""
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id).first()
    if not ir:
        return RedirectResponse(url="/admin", status_code=302)
    if (ir.delivered_code_status or "").strip() == "generating":
        append_integration_job_log(req_id, "delivered_job_log", "운영자 수동 중단")
        ir.delivered_code_status = "failed"
        ir.delivered_code_error = "구현 산출물 생성 작업이 중단되었습니다."
        db.commit()
    return RedirectResponse(url=f"/integration/{req_id}?phase=devcode", status_code=302)


@router.get("/abap-analysis/{analysis_id}/delivery", response_class=HTMLResponse)
def admin_abap_analysis_delivery_page(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db),
    err: str | None = None,
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    row = (
        db.query(models.AbapAnalysisRequest)
        .options(joinedload(models.AbapAnalysisRequest.owner))
        .filter(models.AbapAnalysisRequest.id == analysis_id)
        .first()
    )
    if not row:
        return RedirectResponse(url="/admin", status_code=302)
    fs_body, fs_src_err = resolved_abap_analysis_fs_for_codegen(row)
    can_start_code = bool(fs_body and fs_body.strip()) and (row.delivered_code_status or "").strip() != "generating"
    fs_busy = (row.fs_status or "").strip() == "generating"
    dc_busy = (row.delivered_code_status or "").strip() == "generating"
    gen_busy = fs_busy or dc_busy
    has_fs_material = (row.fs_status or "").strip() == "ready" and (row.fs_text or "").strip()
    has_code_material = rfp_delivered_body_ready(row)
    return templates.TemplateResponse(
        request,
        "admin/abap_analysis_delivery.html",
        {
            "request": request,
            "user": actor,
            "row": row,
            "delivery_err": err,
            "can_start_delivered_code": can_start_code,
            "fs_codegen_preview_error": fs_src_err,
            "job_log_poll_ms": 2500,
            "fs_busy": fs_busy,
            "dc_busy": dc_busy,
            "gen_busy": gen_busy,
            "has_fs_material": has_fs_material,
            "has_code_material": has_code_material,
        },
    )


@router.get("/abap-analysis/{analysis_id}/delivery/generation-log")
def admin_abap_analysis_delivery_generation_log_json(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == analysis_id).first()
    if not row:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse(
        {
            "fs_status": getattr(row, "fs_status", None) or "none",
            "delivered_code_status": getattr(row, "delivered_code_status", None) or "none",
            "fs_job_log": getattr(row, "fs_job_log", None) or "",
            "delivered_job_log": getattr(row, "delivered_job_log", None) or "",
            "fs_error": getattr(row, "fs_error", None) or "",
            "delivered_code_error": getattr(row, "delivered_code_error", None) or "",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/abap-analysis/{analysis_id}/delivery/fs-start")
def admin_abap_analysis_start_fs_generation(
    analysis_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == analysis_id).first()
    if not row:
        return RedirectResponse(url="/admin", status_code=302)
    if (row.fs_status or "").strip() == "generating":
        return RedirectResponse(url=f"/admin/abap-analysis/{analysis_id}/delivery", status_code=302)
    row.fs_status = "generating"
    row.fs_error = None
    row.fs_job_log = None
    db.commit()
    background_tasks.add_task(run_abap_analysis_fs_job, analysis_id)
    return RedirectResponse(url=f"/admin/abap-analysis/{analysis_id}/delivery", status_code=302)


@router.post("/abap-analysis/{analysis_id}/delivery/code-start")
def admin_abap_analysis_start_delivered_code(
    analysis_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    actor = _require_delivery_operator(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == analysis_id).first()
    if not row:
        return RedirectResponse(url="/admin", status_code=302)
    fs_body, fs_err = resolved_abap_analysis_fs_for_codegen(row)
    if fs_err or not (fs_body or "").strip():
        return RedirectResponse(
            url=f"/admin/abap-analysis/{analysis_id}/delivery?err=fs_not_ready",
            status_code=302,
        )
    if (row.delivered_code_status or "").strip() == "generating":
        return RedirectResponse(url=f"/admin/abap-analysis/{analysis_id}/delivery", status_code=302)
    row.delivered_code_status = "generating"
    row.delivered_code_error = None
    row.delivered_job_log = None
    db.commit()
    background_tasks.add_task(run_abap_analysis_delivered_code_job, analysis_id)
    return RedirectResponse(url=f"/admin/abap-analysis/{analysis_id}/delivery", status_code=302)
