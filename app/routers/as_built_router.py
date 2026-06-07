"""최종 구현 산출물(ZIP) 업로드·삭제·다운로드 — 신규/분석·개선/연동."""

from __future__ import annotations

import mimetypes
import os
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import auth, models
from ..as_built_deliverable import (
    AS_BUILT_ALLOWED_EXTENSIONS,
    MAX_AS_BUILT_OTHER_BYTES,
    MAX_AS_BUILT_ZIP_BYTES,
    as_built_entry,
    clear_as_built_entry,
    set_as_built_entry,
    store_as_built_file,
)
from ..database import get_db
from ..request_hub_access import (
    consultant_is_matched_on_request,
    menu_abap_detail_url,
    menu_entity_hub_url,
    user_can_view_request_deliverables,
)
from .. import r2_storage
from ..rfp_download_names import content_disposition_attachment
from ..rfp_hub import rfp_hub_url
from ..integration_hub import integration_hub_url
router = APIRouter()


async def _read_as_built_upload(upload: UploadFile, *, max_bytes: int) -> bytes:
    try:
        await upload.seek(0)
    except Exception:
        pass
    raw = await upload.read()
    if not raw and getattr(upload, "file", None) is not None:
        uf = upload.file
        try:
            uf.seek(0)
        except Exception:
            pass
        raw = uf.read() or b""
    if len(raw) > max_bytes:
        raise ValueError("file_too_large")
    return raw

def _user_may_upload_as_built(db: Session, user, *, kind: str, entity: Any) -> bool:
    if not user or not entity:
        return False
    if getattr(user, "is_admin", False):
        return True
    try:
        uid = int(user.id)
        owner_id = int(entity.user_id)
    except (TypeError, ValueError):
        return False
    if uid == owner_id:
        return True
    if getattr(user, "is_consultant", False):
        return consultant_is_matched_on_request(
            db, consultant_user_id=uid, request_kind=kind, request_id=int(entity.id)
        )
    return False


def _return_url(kind: str, entity_id: int, *, user, owner_id: int) -> str:
    if kind == "rfp":
        return rfp_hub_url(entity_id, "asbuilt") + "#rfp-phase-asbuilt"
    if kind == "integration":
        return menu_entity_hub_url(
            user=user, owner_user_id=owner_id, request_kind="integration",
            request_id=entity_id, phase="asbuilt",
        ) + "#int-phase-asbuilt"
    return menu_abap_detail_url(user=user, owner_user_id=owner_id, request_id=entity_id) + "#abap-phase-asbuilt"


async def _handle_upload(
    *,
    db: Session,
    user,
    entity: Any,
    kind: str,
    upload_file: UploadFile,
    return_to: str | None,
) -> RedirectResponse:
    if not _user_may_upload_as_built(db, user, kind=kind, entity=entity):
        raise HTTPException(status_code=403, detail="forbidden")
    if as_built_entry(entity):
        return RedirectResponse(url=(return_to or "/") + "?as_built_err=already_exists", status_code=303)
    fn = (upload_file.filename or "").strip()
    if not fn:
        return RedirectResponse(url=(return_to or "/") + "?as_built_err=empty_file", status_code=303)
    ext = os.path.splitext(fn)[1].lower()
    if ext not in AS_BUILT_ALLOWED_EXTENSIONS:
        return RedirectResponse(url=(return_to or "/") + "?as_built_err=invalid_file", status_code=303)
    max_bytes = MAX_AS_BUILT_ZIP_BYTES if ext == ".zip" else MAX_AS_BUILT_OTHER_BYTES
    try:
        raw = await _read_as_built_upload(upload_file, max_bytes=max_bytes)
    except ValueError:
        return RedirectResponse(url=(return_to or "/") + "?as_built_err=file_too_large", status_code=303)
    try:
        path, stored_name = store_as_built_file(int(user.id), raw, fn)
    except ValueError as e:
        code = str(e.args[0] if e.args else "invalid_zip")
        return RedirectResponse(url=(return_to or "/") + f"?as_built_err={code}", status_code=303)
    set_as_built_entry(entity, path=path, filename=stored_name)
    db.commit()
    dest = (return_to or "").strip() or _return_url(kind, int(entity.id), user=user, owner_id=int(entity.user_id))
    return RedirectResponse(url=dest + ("&" if "?" in dest else "?") + "as_built_ok=1", status_code=303)


def _handle_delete(*, db: Session, user, entity: Any, kind: str, return_to: str | None) -> RedirectResponse:
    if not _user_may_upload_as_built(db, user, kind=kind, entity=entity):
        raise HTTPException(status_code=403, detail="forbidden")
    clear_as_built_entry(entity)
    db.commit()
    dest = (return_to or "").strip() or _return_url(kind, int(entity.id), user=user, owner_id=int(entity.user_id))
    return RedirectResponse(url=dest, status_code=303)


def _download_response(entity: Any) -> Response:
    ent = as_built_entry(entity)
    if not ent:
        raise HTTPException(status_code=404, detail="not_found")
    raw = r2_storage.read_bytes_from_ref(ent.get("path") or "")
    if not raw:
        raise HTTPException(status_code=404, detail="file_missing")
    fname = (ent.get("filename") or "file").strip()
    ext = os.path.splitext(fname)[1].lower()
    media = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    return Response(
        content=raw,
        media_type=media,
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )


def _request_kind_for_model(model) -> str:
    if model is models.RFP:
        return "rfp"
    if model is models.IntegrationRequest:
        return "integration"
    return "analysis"


def _load_entity(db: Session, model, entity_id: int, user) -> Any | None:
    row = db.query(model).filter(model.id == entity_id).first()
    if not row:
        return None
    if getattr(user, "is_admin", False):
        return row
    if int(row.user_id) == int(user.id):
        return row
    rk = _request_kind_for_model(model)
    if getattr(user, "is_consultant", False) and consultant_is_matched_on_request(
        db, consultant_user_id=user.id, request_kind=rk, request_id=entity_id
    ):
        return row
    return None


def _user_may_download_as_built(db: Session, user, *, kind: str, entity: Any) -> bool:
    if not user or not entity:
        return False
    if getattr(user, "is_admin", False):
        return True
    return user_can_view_request_deliverables(
        db,
        user,
        request_kind=kind,
        request_id=int(entity.id),
        owner_user_id=int(entity.user_id),
        paid_entity=entity,
    )


def _load_entity_for_download(db: Session, model, entity_id: int, user) -> Any | None:
    row = db.query(model).filter(model.id == entity_id).first()
    if not row:
        return None
    rk = _request_kind_for_model(model)
    if not _user_may_download_as_built(db, user, kind=rk, entity=row):
        return None
    return row


@router.post("/rfp/{rfp_id}/as-built-upload")
async def rfp_as_built_upload(
    rfp_id: int,
    file: UploadFile = File(...),
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    rfp = _load_entity(db, models.RFP, rfp_id, user)
    if not rfp:
        raise HTTPException(status_code=404, detail="not_found")
    return await _handle_upload(db=db, user=user, entity=rfp, kind="rfp", upload_file=file, return_to=return_to)


@router.post("/rfp/{rfp_id}/as-built-delete")
async def rfp_as_built_delete(
    rfp_id: int,
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    rfp = _load_entity(db, models.RFP, rfp_id, user)
    if not rfp:
        raise HTTPException(status_code=404, detail="not_found")
    return _handle_delete(db=db, user=user, entity=rfp, kind="rfp", return_to=return_to)


@router.get("/rfp/{rfp_id}/as-built-download")
async def rfp_as_built_download(
    rfp_id: int,
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    rfp = _load_entity_for_download(db, models.RFP, rfp_id, user)
    if not rfp:
        raise HTTPException(status_code=404, detail="not_found")
    return _download_response(rfp)


@router.post("/integration/{req_id}/as-built-upload")
async def integration_as_built_upload(
    req_id: int,
    file: UploadFile = File(...),
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    ir = _load_entity(db, models.IntegrationRequest, req_id, user)
    if not ir:
        raise HTTPException(status_code=404, detail="not_found")
    return await _handle_upload(
        db=db, user=user, entity=ir, kind="integration", upload_file=file, return_to=return_to
    )


@router.post("/integration/{req_id}/as-built-delete")
async def integration_as_built_delete(
    req_id: int,
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    ir = _load_entity(db, models.IntegrationRequest, req_id, user)
    if not ir:
        raise HTTPException(status_code=404, detail="not_found")
    return _handle_delete(db=db, user=user, entity=ir, kind="integration", return_to=return_to)


@router.get("/integration/{req_id}/as-built-download")
async def integration_as_built_download(
    req_id: int,
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    ir = _load_entity_for_download(db, models.IntegrationRequest, req_id, user)
    if not ir:
        raise HTTPException(status_code=404, detail="not_found")
    return _download_response(ir)


@router.post("/abap-analysis/{analysis_id}/as-built-upload")
async def analysis_as_built_upload(
    analysis_id: int,
    file: UploadFile = File(...),
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    row = _load_entity(db, models.AbapAnalysisRequest, analysis_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return await _handle_upload(
        db=db, user=user, entity=row, kind="analysis", upload_file=file, return_to=return_to
    )


@router.post("/abap-analysis/{analysis_id}/as-built-delete")
async def analysis_as_built_delete(
    analysis_id: int,
    return_to: str = Form(""),
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    row = _load_entity(db, models.AbapAnalysisRequest, analysis_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return _handle_delete(db=db, user=user, entity=row, kind="analysis", return_to=return_to)


@router.get("/abap-analysis/{analysis_id}/as-built-download")
async def analysis_as_built_download(
    analysis_id: int,
    user=Depends(auth.require_login),
    db: Session = Depends(get_db),
):
    row = _load_entity_for_download(db, models.AbapAnalysisRequest, analysis_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return _download_response(row)
