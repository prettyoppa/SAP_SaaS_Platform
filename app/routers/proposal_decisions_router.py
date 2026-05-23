"""요청자 §6 확인 필요 사항 — 인라인 최종 결정 저장."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from ..proposal_section6_decisions import (
    load_request_entity_for_decisions,
    parse_section6_open_items,
    save_decisions_payload,
    set_entity_decisions_raw,
)

router = APIRouter(tags=["proposal-decisions"])


def _redirect(return_to: str | None, *, err: str | None = None, ok: bool = False) -> str:
    base = (return_to or "").strip() or "/"
    sep = "&" if "?" in base else "?"
    if ok:
        return f"{base}{sep}section6_decisions=ok"
    if err:
        return f"{base}{sep}section6_decisions_err={quote(err)}"
    return base


def _save_section6_decisions(
  db: Session,
  *,
  request_kind: str,
  request_id: int,
  owner_user_id: int,
  actor_id: int,
  agent_proposal_text: str | None,
  decisions: list[str],
  additional: str,
  return_to: str | None,
) -> RedirectResponse:
    if int(actor_id) != int(owner_user_id):
        return RedirectResponse(url=_redirect(return_to, err="forbidden"), status_code=303)
    entity = load_request_entity_for_decisions(db, request_kind, request_id)
    if not entity:
        return RedirectResponse(url=_redirect(return_to, err="not_found"), status_code=303)
    open_items = parse_section6_open_items(agent_proposal_text or "")
    payload = save_decisions_payload(
        open_items=open_items,
        decisions_by_index=decisions,
        additional=additional,
    )
    set_entity_decisions_raw(entity, payload)
    db.add(entity)
    db.commit()
    return RedirectResponse(url=_redirect(return_to, ok=True), status_code=303)


@router.post("/rfp/{rfp_id}/proposal-section6-decisions")
async def rfp_save_section6_decisions(
    rfp_id: int,
    request: Request,
    return_to: str = Form(""),
    additional: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url=_redirect(return_to, err="not_found"), status_code=303)
    form = await request.form()
    n = max(0, int(form.get("section6_item_count") or 0))
    decisions = [(form.get(f"decision_{i}") or "").strip() for i in range(n)]
    return _save_section6_decisions(
        db,
        request_kind=KIND_RFP,
        request_id=int(rfp_id),
        owner_user_id=int(rfp.user_id),
        actor_id=int(user.id),
        agent_proposal_text=rfp.proposal_text,
        decisions=decisions,
        additional=additional,
        return_to=return_to,
    )


@router.post("/integration/{req_id}/proposal-section6-decisions")
async def integration_save_section6_decisions(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    additional: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id).first()
    if not ir:
        return RedirectResponse(url=_redirect(return_to, err="not_found"), status_code=303)
    form = await request.form()
    n = max(0, int(form.get("section6_item_count") or 0))
    decisions = [(form.get(f"decision_{i}") or "").strip() for i in range(n)]
    return _save_section6_decisions(
        db,
        request_kind=KIND_INTEGRATION,
        request_id=int(req_id),
        owner_user_id=int(ir.user_id),
        actor_id=int(user.id),
        agent_proposal_text=ir.proposal_text,
        decisions=decisions,
        additional=additional,
        return_to=return_to,
    )


@router.post("/abap-analysis/{req_id}/proposal-section6-decisions")
async def abap_save_section6_decisions(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    additional: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    row = (
        db.query(models.AbapAnalysisRequest)
        .filter(models.AbapAnalysisRequest.id == req_id)
        .first()
    )
    if not row:
        return RedirectResponse(url=_redirect(return_to, err="not_found"), status_code=303)
    form = await request.form()
    n = max(0, int(form.get("section6_item_count") or 0))
    decisions = [(form.get(f"decision_{i}") or "").strip() for i in range(n)]
    return _save_section6_decisions(
        db,
        request_kind=KIND_ANALYSIS,
        request_id=int(req_id),
        owner_user_id=int(row.user_id),
        actor_id=int(user.id),
        agent_proposal_text=row.proposal_text,
        decisions=decisions,
        additional=additional,
        return_to=return_to,
    )
