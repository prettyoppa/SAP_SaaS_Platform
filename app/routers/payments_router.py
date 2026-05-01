"""Stripe Checkout·웹훅·결제 완료 리다이렉트."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..paid_tier import rfp_eligible_for_stripe_checkout
from ..stripe_service import (
    construct_webhook_event,
    create_rfp_checkout_session,
    retrieve_checkout_session,
    stripe_keys_configured,
    try_activate_rfp_from_checkout,
)

_log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["payments"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/"


@router.post("/payments/stripe/checkout")
def stripe_checkout_start(
    request: Request,
    rfp_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not stripe_keys_configured():
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?phase=proposal&checkout=unconfigured",
            status_code=302,
        )
    rfp = (
        db.query(models.RFP)
        .filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id)
        .first()
    )
    if not rfp or not rfp_eligible_for_stripe_checkout(rfp):
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=proposal", status_code=302)
    try:
        session = create_rfp_checkout_session(
            rfp_id=rfp_id,
            customer_email=user.email,
            base_url=_base_url(request),
        )
    except Exception:
        _log.exception("stripe checkout create failed rfp_id=%s", rfp_id)
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?phase=proposal&checkout=error",
            status_code=302,
        )
    sid = getattr(session, "id", None)
    url = getattr(session, "url", None)
    if sid:
        rfp.stripe_checkout_session_id = str(sid)
    rfp.paid_engagement_status = "checkout_pending"
    db.commit()
    if not url:
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?phase=proposal&checkout=error",
            status_code=302,
        )
    return RedirectResponse(url=url, status_code=303)


@router.get("/rfp/{rfp_id}/billing/confirm")
def billing_confirm_redirect(
    rfp_id: int,
    request: Request,
    session_id: str | None = None,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = (
        db.query(models.RFP)
        .filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id)
        .first()
    )
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    if not session_id or not session_id.strip():
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?phase=proposal&checkout=missing_session",
            status_code=302,
        )
    try:
        sess = retrieve_checkout_session(session_id.strip())
        try_activate_rfp_from_checkout(db, sess, expect_rfp_id=rfp_id)
    except Exception:
        _log.exception("billing confirm verify failed rfp_id=%s", rfp_id)
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?phase=proposal&checkout=verify_failed",
            status_code=302,
        )
    return RedirectResponse(
        url=f"/rfp/{rfp_id}?phase=proposal&checkout=success",
        status_code=302,
    )


@router.post("/payments/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = construct_webhook_event(payload, sig)
    except Exception:
        _log.warning("stripe webhook signature failed")
        return PlainTextResponse("invalid signature", status_code=400)

    if event.type != "checkout.session.completed":
        return PlainTextResponse("ok", status_code=200)

    sess = event.data.object
    try:
        try_activate_rfp_from_checkout(db, sess)
    except Exception:
        _log.exception("stripe webhook activate failed")
    return PlainTextResponse("ok", status_code=200)
