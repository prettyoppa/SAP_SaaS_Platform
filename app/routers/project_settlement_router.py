"""납품 대금 — 허브 연동·결제·컨펌."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..payment_claim_service import create_project_settlement_bank_claim
from ..payment_claim_service import cancel_payment_claim
from ..payment_purpose import PURPOSE_PROJECT_SETTLEMENT
from ..payment_providers.portone_service import create_pending_transaction
from ..payment_providers.portone_settings import portone_checkout_ready
from ..project_settlement import (
    PAYMENT_METHOD_BANK,
    PAYMENT_METHOD_PORTONE,
    STATUS_AWAITING_PAYMENT,
    accept_amount,
    confirm_delivery,
    get_or_create_settlement,
    mark_payout_completed,
    normalize_payment_method,
    normalize_request_kind,
    propose_amount,
    status_label_en,
    status_label_ko,
    user_can_view_settlement,
)
from ..project_settlement_settings import (
    format_fee_percent,
    get_platform_fee_bps,
    set_platform_fee_bps,
)
from ..templates_config import templates

_log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["project-settlement"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/"


def _hub_url(kind: str, request_id: int, *, anchor: str = "settlement") -> str:
    if kind == "rfp":
        return f"/rfp/{int(request_id)}?phase=settlement#{kind}-phase-settlement"
    if kind == "analysis":
        return f"/abap-analysis/{int(request_id)}?phase=settlement#abap-phase-settlement"
    if kind == "integration":
        return f"/integration/{int(request_id)}?phase=settlement#int-phase-settlement"
    return f"/?phase=settlement"


def _redirect_hub(kind: str, request_id: int, **q: str) -> str:
    base = _hub_url(kind, request_id)
    if not q:
        return base
    sep = "&" if "?" in base else "?"
    parts = [f"{k}={quote(str(v), safe='')}" for k, v in q.items() if v]
    return base + sep + "&".join(parts)


@router.get("/settlement/{kind}/{request_id}", response_class=HTMLResponse)
def settlement_redirect_to_hub(
    kind: str,
    request_id: int,
    request: Request,
    settlement_ok: str | None = None,
    settlement_err: str | None = None,
    paymentId: str | None = None,
    db: Session = Depends(get_db),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException404()
    user = auth.get_current_user(request, db)
    pid = (paymentId or "").strip()
    if pid and user:
        from ..payment_providers.portone_service import sync_payment

        try:
            sync_payment(db, pid)
            settlement_ok = settlement_ok or "portone"
        except Exception:
            _log.exception("settlement portone return sync failed")
            settlement_err = settlement_err or "portone_verify_failed"
    q: dict[str, str] = {}
    if settlement_ok:
        q["settlement_ok"] = settlement_ok
    if settlement_err:
        q["settlement_err"] = settlement_err
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), **q), status_code=303)


def HTTPException404():
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="not_found")


@router.post("/settlement/{kind}/{request_id}/propose")
def settlement_propose(
    kind: str,
    request_id: int,
    request: Request,
    gross_amount_krw: str = Form("0"),
    use_platform_payment: str | None = Form(None),
    payment_method: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    raw_amt = (gross_amount_krw or "").strip().replace(",", "")
    try:
        amt = int(raw_amt) if raw_amt else 0
    except ValueError:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="invalid_amount"), status_code=303)
    err = propose_amount(
        db,
        user,
        row,
        gross_amount_krw=amt,
        use_platform_payment=(use_platform_payment or "").strip().lower() in ("1", "true", "on", "yes"),
        payment_method=(payment_method or "").strip(),
    )
    db.commit()
    return RedirectResponse(
        url=_redirect_hub(norm, int(request_id), settlement_err=err or ""),
        status_code=303,
    )


@router.post("/settlement/{kind}/{request_id}/accept-amount")
def settlement_accept_amount(
    kind: str,
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    err = accept_amount(db, user, row)
    db.commit()
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err or ""), status_code=303)


@router.post("/settlement/{kind}/{request_id}/confirm-delivery")
def settlement_confirm_delivery(
    kind: str,
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    err = confirm_delivery(db, user, row)
    db.commit()
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err or ""), status_code=303)


@router.get("/settlement/{kind}/{request_id}/pay-portone")
def settlement_pay_portone(
    request: Request,
    kind: str,
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user or int(user.id) != int(row.owner_user_id):
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    if row.status != STATUS_AWAITING_PAYMENT or not row.gross_amount_krw:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="not_ready"), status_code=303)
    if normalize_payment_method(row.payment_method) != PAYMENT_METHOD_PORTONE:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="wrong_payment_method"), status_code=303)
    if not portone_checkout_ready():
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="portone_unconfigured"), status_code=303)
    return_url = _redirect_hub(norm, int(request_id), settlement_ok="portone")
    txn = create_pending_transaction(
        db,
        user,
        purpose=PURPOSE_PROJECT_SETTLEMENT,
        purpose_ref_id=int(row.id),
        amount_krw=int(row.gross_amount_krw),
        return_url=return_url,
        cancel_url=_redirect_hub(norm, int(request_id), settlement_err="portone_cancelled"),
    )
    if not txn:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="portone_error"), status_code=303)
    db.commit()
    return RedirectResponse(url=f"/payments/portone/checkout/{int(txn.id)}", status_code=303)


@router.post("/settlement/{kind}/{request_id}/bank-claim")
def settlement_bank_claim(
    kind: str,
    request_id: int,
    depositor_name: str = Form(""),
    transfer_date: str = Form(""),
    member_note: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    if normalize_payment_method(row.payment_method) != PAYMENT_METHOD_BANK:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="wrong_payment_method"), status_code=303)
    td = None
    if (transfer_date or "").strip():
        try:
            from datetime import datetime

            td = datetime.fromisoformat(transfer_date.strip())
        except ValueError:
            return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="bad_date"), status_code=303)
    claim, err = create_project_settlement_bank_claim(
        db, user, row, depositor_name=depositor_name, transfer_date=td, member_note=member_note
    )
    if err:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err), status_code=303)
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_ok="bank_submitted"), status_code=303)


@router.post("/settlement/{kind}/{request_id}/bank-claim/{claim_id}/cancel")
def settlement_bank_claim_cancel(
    kind: str,
    request_id: int,
    claim_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user or int(user.id) != int(row.owner_user_id):
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    err = cancel_payment_claim(db, user, int(claim_id))
    db.commit()
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err or ""), status_code=303)


@router.post("/settlement/{kind}/{request_id}/payout-profile")
def settlement_save_payout_profile(
    kind: str,
    request_id: int,
    account_holder_name: str = Form(""),
    bank_name: str = Form(""),
    account_number: str = Form(""),
    country_code: str = Form("KR"),
    swift_bic: str = Form(""),
    wise_recipient_hint: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user or int(user.id) != int(row.consultant_user_id):
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    prof = (
        db.query(models.ConsultantPayoutProfile)
        .filter(
            models.ConsultantPayoutProfile.user_id == int(user.id),
            models.ConsultantPayoutProfile.is_default.is_(True),
        )
        .first()
    )
    if not prof:
        prof = models.ConsultantPayoutProfile(user_id=int(user.id), is_default=True)
        db.add(prof)
    prof.account_holder_name = (account_holder_name or "")[:200]
    prof.bank_name = (bank_name or "")[:200]
    prof.account_number = (account_number or "")[:64]
    prof.country_code = (country_code or "KR").strip().upper()[:2] or "KR"
    prof.swift_bic = (swift_bic or "").strip()[:32] or None
    prof.wise_recipient_hint = (wise_recipient_hint or "").strip()[:256] or None
    db.commit()
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_ok="profile_saved"), status_code=303)


@router.post("/admin/settlement/{settlement_id}/mark-payout")
def admin_mark_payout(
    settlement_id: int,
    admin_note: str = Form(""),
    external_ref: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    if not user or not user.is_admin:
        return RedirectResponse(url="/admin", status_code=303)
    row = db.query(models.ProjectSettlement).filter(models.ProjectSettlement.id == int(settlement_id)).first()
    if not row:
        return RedirectResponse(url="/admin/project-settlements", status_code=303)
    err = mark_payout_completed(db, user, row, note=admin_note, external_ref=external_ref)
    db.commit()
    return RedirectResponse(
        url=f"/admin/project-settlements?ok={'' if not err else err}",
        status_code=303,
    )


@router.get("/admin/project-settlements", response_class=HTMLResponse)
def admin_project_settlements_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    rows = (
        db.query(models.ProjectSettlement)
        .order_by(models.ProjectSettlement.updated_at.desc())
        .limit(100)
        .all()
    )
    user_ids = {int(r.owner_user_id) for r in rows} | {int(r.consultant_user_id) for r in rows}
    users_by_id: dict[int, models.User] = {}
    if user_ids:
        for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all():
            users_by_id[int(u.id)] = u
    fee_bps = get_platform_fee_bps(db)
    return templates.TemplateResponse(
        request,
        "admin/project_settlements.html",
        {
            "request": request,
            "user": user,
            "settlements": rows,
            "users_by_id": users_by_id,
            "fee_bps": fee_bps,
            "fee_percent": format_fee_percent(fee_bps),
            "status_label_ko": status_label_ko,
            "status_label_en": status_label_en,
            "saved": request.query_params.get("saved") == "1",
            "ok": (request.query_params.get("ok") or "").strip(),
        },
    )


@router.post("/admin/project-settlement-fee")
def admin_project_settlement_fee_save(
    request: Request,
    fee_percent: str = Form("10"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    try:
        pct = float((fee_percent or "10").strip().replace(",", ""))
    except ValueError:
        return RedirectResponse(url="/admin/project-settlements?ok=bad_fee", status_code=303)
    bps = int(round(pct * 100))
    set_platform_fee_bps(db, bps)
    db.commit()
    return RedirectResponse(url="/admin/project-settlements?saved=1", status_code=303)


