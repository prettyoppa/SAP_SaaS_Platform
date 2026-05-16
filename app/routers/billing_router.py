"""회원: 계좌이체 입금 신청."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..bank_transfer_settings import ALL_BANK_BILLING_SETTING_KEYS
from ..database import get_db
from ..payment_claim_service import (
    account_kind_for_user,
    cancel_payment_claim,
    claims_for_user,
    create_payment_claim,
    expected_amount_minor,
    user_pending_claim,
)
from ..subscription_catalog import (
    CONSULTANT_PLAN_PUBLIC_ORDER,
    MEMBER_PLAN_PUBLIC_ORDER,
    resolve_plan_monthly_prices,
)
from ..subscription_quota import user_subscription_plan_display_names
from ..templates_config import templates

router = APIRouter(tags=["billing"])


def _load_billing_settings(db: Session) -> dict[str, str]:
    keys = set(ALL_BANK_BILLING_SETTING_KEYS)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).filter(models.SiteSettings.key.in_(keys)).all()}
    return {k: (raw.get(k) or "").strip() for k in ALL_BANK_BILLING_SETTING_KEYS}


def _parse_transfer_date(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


@router.get("/account/billing", response_class=HTMLResponse)
def account_billing_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/billing", status_code=302)
    settings = _load_billing_settings(db)
    kind = account_kind_for_user(user)
    order = CONSULTANT_PLAN_PUBLIC_ORDER if kind == "consultant" else MEMBER_PLAN_PUBLIC_ORDER
    plans = (
        db.query(models.SubscriptionPlan)
        .filter(
            models.SubscriptionPlan.account_kind == kind,
            models.SubscriptionPlan.is_active.is_(True),
            models.SubscriptionPlan.code.in_(list(order)),
        )
        .all()
    )
    plans_by_code = {p.code: p for p in plans}
    plan_options: list[dict] = []
    for code in order:
        p = plans_by_code.get(code)
        if not p or code == "experience":
            continue
        krw, usdc = resolve_plan_monthly_prices(p)
        plan_options.append(
            {
                "code": code,
                "name": p.display_name_ko,
                "krw": krw,
                "usd_cents": usdc,
            }
        )
    sp_ko, sp_en = user_subscription_plan_display_names(db, user)
    err = (request.query_params.get("err") or "").strip()
    ok = request.query_params.get("ok") == "1"
    return templates.TemplateResponse(
        request,
        "account_billing.html",
        {
            "user": user,
            "settings": settings,
            "plan_options": plan_options,
            "account_kind": kind,
            "claims": claims_for_user(db, user.id),
            "pending_claim": user_pending_claim(db, user.id),
            "subscription_plan_display_ko": sp_ko,
            "subscription_plan_display_en": sp_en,
            "billing_err": err,
            "billing_ok": ok,
        },
    )


@router.post("/account/billing/claim")
def account_billing_claim_post(
    request: Request,
    db: Session = Depends(get_db),
    billing_country: str = Form("KR"),
    plan_code: str = Form(""),
    amount_minor: str = Form(""),
    depositor_name: str = Form(""),
    transfer_date: str = Form(""),
    member_note: str = Form(""),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/billing", status_code=302)
    try:
        amt = int((amount_minor or "").replace(",", "").strip())
    except ValueError:
        return RedirectResponse(url="/account/billing?err=invalid_amount", status_code=303)
    err, _row = create_payment_claim(
        db,
        user,
        billing_country=billing_country,
        plan_code=plan_code,
        amount_minor=amt,
        depositor_name=depositor_name,
        transfer_date=_parse_transfer_date(transfer_date),
        member_note=member_note,
    )
    if err:
        from urllib.parse import quote

        return RedirectResponse(url=f"/account/billing?err={quote(err)}", status_code=303)
    return RedirectResponse(url="/account/billing?ok=1", status_code=303)


@router.post("/account/billing/claim/{claim_id}/cancel")
def account_billing_claim_cancel(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/billing", status_code=302)
    err = cancel_payment_claim(db, user, claim_id)
    if err:
        from urllib.parse import quote

        return RedirectResponse(url=f"/account/billing?err={quote(err)}", status_code=303)
    return RedirectResponse(url="/account/billing?ok=1", status_code=303)
