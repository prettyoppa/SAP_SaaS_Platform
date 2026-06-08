"""납품 대금 — 허브 연동·결제·컨펌."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..ai_wallet import parse_usd_input_to_cents, usd_krw_rate_from_db
from ..billing_currency import user_prefers_usd_payments
from ..database import get_db
from ..payment_claim_service import create_project_settlement_bank_claim
from ..payment_claim_service import cancel_payment_claim
from ..payment_purpose import PURPOSE_PROJECT_SETTLEMENT
from ..payment_providers.portone_service import create_pending_transaction
from ..payment_providers.portone_settings import portone_checkout_ready, portone_paypal_channel_key
from ..project_settlement import (
    PAYMENT_METHOD_BANK,
    PAYMENT_METHOD_PORTONE,
    STATUS_AWAITING_PAYMENT,
    apply_requester_payment_terms,
    confirm_delivery,
    get_or_create_settlement,
    mark_payout_completed,
    normalize_payment_method,
    normalize_request_kind,
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


def _parse_amount_krw(raw: str) -> int | None:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return None


@router.post("/settlement/{kind}/{request_id}/pay-portone")
def settlement_pay_portone_post(
    kind: str,
    request_id: int,
    request: Request,
    gross_amount_krw: str = Form("0"),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    row = get_or_create_settlement(db, request_kind=norm, request_id=int(request_id))
    if not row or not user:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="forbidden"), status_code=303)
    payment_usd = user_prefers_usd_payments(user)
    usd_cents: int | None = None
    if payment_usd:
        usd_cents = parse_usd_input_to_cents(gross_amount_krw)
        if usd_cents is None:
            return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="invalid_amount"), status_code=303)
        rate = float(usd_krw_rate_from_db(db) or 1350.0)
        gross_krw = max(1, int(round((usd_cents / 100.0) * rate)))
        err = apply_requester_payment_terms(
            db,
            user,
            row,
            gross_amount_krw=gross_krw,
            payment_method=PAYMENT_METHOD_PORTONE,
            payment_currency="USD",
        )
    else:
        amt = _parse_amount_krw(gross_amount_krw)
        if amt is None or amt <= 0:
            return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="invalid_amount"), status_code=303)
        err = apply_requester_payment_terms(
            db,
            user,
            row,
            gross_amount_krw=amt,
            payment_method=PAYMENT_METHOD_PORTONE,
            payment_currency="KRW",
        )
    if err:
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err), status_code=303)
    if row.status != STATUS_AWAITING_PAYMENT:
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="not_ready"), status_code=303)
    if not portone_checkout_ready():
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="portone_unconfigured"), status_code=303)
    if payment_usd and not portone_paypal_channel_key():
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="paypal_unconfigured"), status_code=303)
    return_url = _redirect_hub(norm, int(request_id), settlement_ok="portone")
    if payment_usd:
        txn = create_pending_transaction(
            db,
            user,
            purpose=PURPOSE_PROJECT_SETTLEMENT,
            purpose_ref_id=int(row.id),
            amount_krw=int(usd_cents or 0),
            return_url=return_url,
            cancel_url=_redirect_hub(norm, int(request_id), settlement_err="portone_cancelled"),
            currency="USD",
        )
    else:
        txn = create_pending_transaction(
            db,
            user,
            purpose=PURPOSE_PROJECT_SETTLEMENT,
            purpose_ref_id=int(row.id),
            amount_krw=int(row.gross_amount_krw),
            return_url=return_url,
            cancel_url=_redirect_hub(norm, int(request_id), settlement_err="portone_cancelled"),
            currency="KRW",
        )
    if not txn:
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="portone_error"), status_code=303)
    db.commit()
    return RedirectResponse(url=f"/payments/portone/checkout/{int(txn.id)}", status_code=303)


@router.get("/settlement/{kind}/{request_id}/pay-portone")
def settlement_pay_portone(
    kind: str,
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind) or ""
    return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="use_post"), status_code=303)


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


@router.post("/settlement/{kind}/{request_id}/bank-claim")
def settlement_bank_claim(
    kind: str,
    request_id: int,
    gross_amount_krw: str = Form("0"),
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
    amt = _parse_amount_krw(gross_amount_krw)
    if amt is None or amt <= 0:
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err="invalid_amount"), status_code=303)
    err = apply_requester_payment_terms(
        db,
        user,
        row,
        gross_amount_krw=amt,
        payment_method=PAYMENT_METHOD_BANK,
    )
    if err:
        db.commit()
        return RedirectResponse(url=_redirect_hub(norm, int(request_id), settlement_err=err), status_code=303)
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


