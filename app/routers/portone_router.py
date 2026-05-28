"""PortOne V2 — 결제창·동기화·웹훅."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..payment_fulfillment import TXN_STATUS_PAID
from ..payment_providers.portone_service import (
    create_pending_transaction,
    order_name_for_transaction,
    sync_payment,
    verify_webhook,
    webhook_payment_id,
)
from ..payment_providers.portone_checkout import resolve_portone_checkout
from ..payment_providers.portone_settings import (
    portone_checkout_ready,
    portone_store_id,
    portone_webhook_ready,
)
from ..templates_config import templates

_log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["portone"])


def _user_owns_transaction(user: models.User, txn: models.PaymentTransaction) -> bool:
    return int(user.id) == int(txn.user_id)


@router.get("/payments/portone/checkout/{txn_id}", response_class=HTMLResponse)
def portone_checkout_page(
    txn_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not portone_checkout_ready():
        return RedirectResponse(url="/?err=portone_unconfigured", status_code=303)
    txn = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.id == int(txn_id)).first()
    if not txn or not _user_owns_transaction(user, txn):
        return RedirectResponse(url="/", status_code=303)
    if (txn.status or "") == TXN_STATUS_PAID:
        return RedirectResponse(url=txn.return_url or "/", status_code=303)
    from urllib.parse import quote

    base = str(request.base_url).rstrip("/")
    redirect_url = f"{base}/payments/portone/return?paymentId={quote(txn.payment_id)}"
    pay_q = (request.query_params.get("pay") or "").strip().lower()
    checkout = resolve_portone_checkout(
        user,
        txn,
        db,
        paypal_query_override=(pay_q == "paypal"),
    )
    return templates.TemplateResponse(
        request,
        "payments/portone_checkout.html",
        {
            "request": request,
            "user": user,
            "txn": txn,
            "store_id": portone_store_id(),
            "channel_key": checkout.channel_key,
            "order_name": order_name_for_transaction(txn),
            "complete_url": "/payments/portone/complete",
            "redirect_url": redirect_url,
            "return_url": txn.return_url or "/",
            "cancel_url": txn.cancel_url or txn.return_url or "/",
            "checkout_mode": checkout.checkout_mode,
            "checkout_currency": checkout.checkout_currency,
            "checkout_amount": checkout.checkout_amount,
            "paypal_enabled": checkout.paypal_channel_configured,
            "paypal_unavailable_for_usd": checkout.paypal_unavailable_for_usd,
            "use_paypal": checkout.use_paypal,
        },
    )


@router.post("/payments/portone/complete")
async def portone_complete(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_body"}, status_code=400)
    payment_id = (body.get("paymentId") or body.get("payment_id") or "").strip()
    if not payment_id:
        return JSONResponse({"ok": False, "error": "missing_payment_id"}, status_code=400)
    txn = (
        db.query(models.PaymentTransaction)
        .filter(
            models.PaymentTransaction.payment_id == payment_id,
            models.PaymentTransaction.user_id == int(user.id),
        )
        .first()
    )
    if not txn:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    synced = sync_payment(db, payment_id)
    if not synced or (synced.status or "") != TXN_STATUS_PAID:
        return JSONResponse(
            {"ok": False, "error": "not_paid", "return_url": txn.return_url},
            status_code=400,
        )
    return JSONResponse({"ok": True, "return_url": synced.return_url or "/"})


@router.get("/payments/portone/return")
def portone_return(
    request: Request,
    paymentId: str | None = None,
    payment_id: str | None = None,
    db: Session = Depends(get_db),
):
    """결제창 리다이렉트 복귀 — 서버 동기화 후 return_url로 이동."""
    pid = (paymentId or payment_id or "").strip()
    user = auth.get_current_user(request, db)
    fallback = "/"
    if pid and user:
        txn = (
            db.query(models.PaymentTransaction)
            .filter(
                models.PaymentTransaction.payment_id == pid,
                models.PaymentTransaction.user_id == int(user.id),
            )
            .first()
        )
        if txn:
            fallback = txn.return_url or fallback
            sync_payment(db, pid)
    return RedirectResponse(url=fallback, status_code=303)


@router.post("/payments/portone/webhook")
async def portone_webhook(request: Request, db: Session = Depends(get_db)):
    if not portone_webhook_ready():
        return PlainTextResponse("webhook not configured", status_code=503)
    payload = await request.body()
    text = payload.decode("utf-8")
    headers = {k: v for k, v in request.headers.items()}
    try:
        webhook = verify_webhook(text, headers)
    except Exception:
        _log.warning("portone webhook verify failed")
        return PlainTextResponse("invalid", status_code=400)
    pid = webhook_payment_id(webhook)
    if pid:
        try:
            sync_payment(db, pid)
        except Exception:
            _log.exception("portone webhook sync failed payment_id=%s", pid)
    return PlainTextResponse("ok", status_code=200)
