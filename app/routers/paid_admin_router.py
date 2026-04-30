"""관리자: 유료 RFP 배송(FS·납품 코드) — 생성 트리거 전용."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from .. import auth, models
from ..database import get_db
from ..paid_generation import run_delivered_code_job, run_fs_generation_job
from ..paid_tier import paid_engagement_is_active
from ..templates_config import templates
from ..routers.interview_router import _messages_to_list

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
        .options(joinedload(models.RFP.messages), joinedload(models.RFP.owner))
        .filter(models.RFP.id == rfp_id)
        .first()
    )
    if not rfp:
        return RedirectResponse(url="/admin", status_code=302)

    msgs = sorted(_messages_to_list(rfp.messages), key=lambda x: (x["round_number"], x["id"]))

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
        },
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
    if (rfp.fs_status or "") != "ready" or not ((rfp.fs_text or "").strip()):
        return RedirectResponse(
            url=f"/admin/rfp/{rfp_id}/delivery?err=fs_not_ready",
            status_code=302,
        )
    if (rfp.delivered_code_status or "") == "generating":
        return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
    rfp.delivered_code_status = "generating"
    rfp.delivered_code_error = None
    db.commit()
    background_tasks.add_task(run_delivered_code_job, rfp_id)
    return RedirectResponse(url=f"/admin/rfp/{rfp_id}/delivery", status_code=302)
