"""요청자 제안서 .md 첨부 업로드·삭제 (3개 메뉴 공통)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models, r2_storage
from ..database import get_db
from ..delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from ..delivery_proposal_supplements import (
    DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES,
    list_delivery_proposal_supplements,
    proposal_supplement_member_paths,
)
from ..routers.rfp_router import _read_upload_limited, _store_rfp_file

router = APIRouter(tags=["proposal-supplements"])


def _delete_supplement_blob(path: str) -> None:
    if not path:
        return
    try:
        r2_storage.delete_ref(path)
    except Exception:
        pass


def _redirect_after_upload(
    request_kind: str,
    request_id: int,
    *,
    err: str | None = None,
    return_to: str | None = None,
) -> str:
    if return_to and return_to.startswith("/") and "//" not in return_to:
        url = return_to
    else:
        url = proposal_supplement_member_paths(request_kind, request_id)[
            "proposal_supplement_upload_url"
        ].replace("/proposal-supplement-upload", "")
    if err:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}prop_err={err}"
    return url


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        return True
    return (request.headers.get("x-requested-with") or "").lower() == "fetch"


async def _handle_proposal_supplement_upload(
    *,
    request: Request,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    actor_id: int,
    db: Session,
    files: list[UploadFile],
    return_to: str | None,
) -> JSONResponse | RedirectResponse:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    upload_list = files if isinstance(files, list) else [files]

    def fail(err: str, status: int = 400):
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": err}, status_code=status)
        return RedirectResponse(
            url=_redirect_after_upload(kind, rid, err=err, return_to=return_to),
            status_code=302,
        )

    if not upload_list:
        return fail("prop_upload_no_name")

    pending: list[tuple[bytes, str]] = []
    for file in upload_list:
        if not file.filename:
            continue
        ext = os.path.splitext(file.filename)[1].lower()
        if ext != ".md":
            return fail("prop_bad_ext")
        try:
            raw = await _read_upload_limited(file)
        except ValueError:
            return fail("prop_too_large")
        if raw:
            pending.append((raw, file.filename or "proposal.md"))

    if not pending:
        return fail("prop_upload_empty")

    existing_n = len(list_delivery_proposal_supplements(db, kind, rid))
    if existing_n + len(pending) > DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES:
        return fail("prop_upload_limit")
    if len(pending) > DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES:
        return fail("prop_upload_batch_limit")

    rfp_fk = rid if kind == KIND_RFP else None
    saved: list[dict] = []
    for raw, fname in pending:
        path_stored, fname_stored = _store_rfp_file(int(owner_user_id), ".md", raw, fname)
        row = models.RfpProposalSupplement(
            rfp_id=rfp_fk,
            request_kind=kind,
            request_id=rid,
            stored_path=path_stored,
            filename=fname_stored,
            uploaded_by_user_id=actor_id,
        )
        db.add(row)
        db.flush()
        saved.append({"id": row.id, "filename": fname_stored})
    db.commit()

    if _wants_json(request):
        return JSONResponse({"ok": True, "uploaded": len(saved), "files": saved})
    return RedirectResponse(
        url=_redirect_after_upload(kind, rid, return_to=return_to),
        status_code=302,
    )


def _delete_proposal_supplement_row(
    db: Session, *, request_kind: str, request_id: int, supplement_id: int
) -> bool:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    sup = (
        db.query(models.RfpProposalSupplement)
        .filter(
            models.RfpProposalSupplement.id == supplement_id,
            models.RfpProposalSupplement.request_kind == kind,
            models.RfpProposalSupplement.request_id == rid,
        )
        .first()
    )
    if not sup:
        return False
    p = sup.stored_path
    db.delete(sup)
    db.commit()
    _delete_supplement_blob(p or "")
    return True


def _owner_context(
    db: Session, request_kind: str, request_id: int
) -> tuple[int | None, int | None]:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == KIND_RFP:
        row = db.query(models.RFP).filter(models.RFP.id == rid).first()
        return (int(row.user_id), rid) if row and row.user_id else (None, None)
    if kind == KIND_ANALYSIS:
        row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
        return (int(row.user_id), rid) if row and row.user_id else (None, None)
    if kind == KIND_INTEGRATION:
        row = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == rid).first()
        return (int(row.user_id), rid) if row and row.user_id else (None, None)
    return None, None


def _require_owner(request: Request, db: Session, request_kind: str, request_id: int):
    user = auth.get_current_user(request, db)
    if not user:
        return None, None
    owner_id, _ = _owner_context(db, request_kind, request_id)
    if owner_id is None:
        return None, None
    if int(user.id) != int(owner_id) and not getattr(user, "is_admin", False):
        return None, None
    return user, owner_id


@router.post("/rfp/{rfp_id}/proposal-supplement-upload")
async def rfp_upload_proposal_supplement(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(...),
    return_to: str | None = Form(None),
):
    user, owner_id = _require_owner(request, db, KIND_RFP, rfp_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return await _handle_proposal_supplement_upload(
        request=request,
        request_kind=KIND_RFP,
        request_id=rfp_id,
        owner_user_id=int(owner_id),
        actor_id=int(user.id),
        db=db,
        files=files,
        return_to=return_to,
    )


@router.post("/rfp/{rfp_id}/proposal-supplement/{supplement_id}/delete")
def rfp_delete_proposal_supplement(
    rfp_id: int,
    supplement_id: int,
    request: Request,
    db: Session = Depends(get_db),
    return_to: str | None = Form(None),
):
    user, _ = _require_owner(request, db, KIND_RFP, rfp_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    _delete_proposal_supplement_row(
        db, request_kind=KIND_RFP, request_id=rfp_id, supplement_id=supplement_id
    )
    return RedirectResponse(
        url=_redirect_after_upload(KIND_RFP, rfp_id, return_to=return_to),
        status_code=302,
    )


@router.post("/abap-analysis/{req_id}/proposal-supplement-upload")
async def abap_upload_proposal_supplement(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(...),
    return_to: str | None = Form(None),
):
    user, owner_id = _require_owner(request, db, KIND_ANALYSIS, req_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return await _handle_proposal_supplement_upload(
        request=request,
        request_kind=KIND_ANALYSIS,
        request_id=req_id,
        owner_user_id=int(owner_id),
        actor_id=int(user.id),
        db=db,
        files=files,
        return_to=return_to,
    )


@router.post("/abap-analysis/{req_id}/proposal-supplement/{supplement_id}/delete")
def abap_delete_proposal_supplement(
    req_id: int,
    supplement_id: int,
    request: Request,
    db: Session = Depends(get_db),
    return_to: str | None = Form(None),
):
    user, _ = _require_owner(request, db, KIND_ANALYSIS, req_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    _delete_proposal_supplement_row(
        db, request_kind=KIND_ANALYSIS, request_id=req_id, supplement_id=supplement_id
    )
    return RedirectResponse(
        url=_redirect_after_upload(KIND_ANALYSIS, req_id, return_to=return_to),
        status_code=302,
    )


@router.post("/integration/{req_id}/proposal-supplement-upload")
async def integration_upload_proposal_supplement(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(...),
    return_to: str | None = Form(None),
):
    user, owner_id = _require_owner(request, db, KIND_INTEGRATION, req_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return await _handle_proposal_supplement_upload(
        request=request,
        request_kind=KIND_INTEGRATION,
        request_id=req_id,
        owner_user_id=int(owner_id),
        actor_id=int(user.id),
        db=db,
        files=files,
        return_to=return_to,
    )


@router.post("/integration/{req_id}/proposal-supplement/{supplement_id}/delete")
def integration_delete_proposal_supplement(
    req_id: int,
    supplement_id: int,
    request: Request,
    db: Session = Depends(get_db),
    return_to: str | None = Form(None),
):
    user, _ = _require_owner(request, db, KIND_INTEGRATION, req_id)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    _delete_proposal_supplement_row(
        db, request_kind=KIND_INTEGRATION, request_id=req_id, supplement_id=supplement_id
    )
    return RedirectResponse(
        url=_redirect_after_upload(KIND_INTEGRATION, req_id, return_to=return_to),
        status_code=302,
    )
