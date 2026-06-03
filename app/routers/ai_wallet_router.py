"""회원: AI 잔액 · 사용량 · 계좌이체 충전."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..ai_usage_recorder import (
    STAGE_LABEL_EN,
    STAGE_LABEL_KO,
    aggregate_usage_for_user,
    format_krw_from_micro,
    format_token_count,
    format_usd_from_micro,
    member_usage_log_rows,
)
from ..ai_wallet import (
    build_wallet_topup_history_rows,
    wallet_balance_usd_display,
    krw_from_usage_usd_micro,
    min_topup_krw,
    min_topup_usd_cents,
    parse_usd_input_to_cents,
    member_wallet_balance_display_krw,
    wallet_balance_krw,
)
from ..billing_currency import user_prefers_usd_payments
from ..bank_transfer_settings import BANK_TRANSFER_SETTING_KEYS
from ..database import get_db
from ..payment_claim_messages import ERR_AMOUNT_MISMATCH
from ..payment_purpose import PURPOSE_AI_WALLET_TOPUP
from ..payment_providers.portone_service import create_pending_transaction, sync_user_portone_transactions
from ..payment_providers.portone_settings import portone_checkout_ready, portone_paypal_channel_key
from ..payment_claim_service import (
    cancel_payment_claim,
    create_wallet_topup_claim,
    user_pending_claim,
)
from ..templates_config import templates

router = APIRouter(tags=["ai-wallet"])

_AI_CREDITS_PATH = "/account/ai-credits"


def _load_bank_settings(db: Session) -> dict[str, str]:
    keys = set(BANK_TRANSFER_SETTING_KEYS)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).filter(models.SiteSettings.key.in_(keys)).all()}
    base = {k: (raw.get(k) or "").strip() for k in BANK_TRANSFER_SETTING_KEYS}
    from ..site_settings_locale import enrich_site_settings

    return enrich_site_settings(db, base, scope="billing")


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


def _usage_context(db: Session, user: models.User) -> dict:
    usage_agg = aggregate_usage_for_user(db, user.id)
    raw_settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    try:
        usd_krw = float((raw_settings.get("usd_krw_rate") or "1350").strip().replace(",", ""))
    except ValueError:
        usd_krw = 1350.0
    total_micro = int(usage_agg.get("total_usd_micro") or 0)
    usage_krw_int = krw_from_usage_usd_micro(total_micro, usd_krw)
    stage_rows = []
    for st, micro in sorted(
        (usage_agg.get("by_stage_micro") or {}).items(),
        key=lambda x: -x[1],
    ):
        pct = (100.0 * micro / total_micro) if total_micro else 0.0
        stage_rows.append(
            {
                "stage": st,
                "label": STAGE_LABEL_KO.get(st, st),
                "label_en": STAGE_LABEL_EN.get(st, st),
                "usd": format_usd_from_micro(micro),
                "krw": format_krw_from_micro(micro, usd_krw),
                "krw_int": krw_from_usage_usd_micro(micro, usd_krw),
                "pct": round(pct, 1),
            }
        )
    log_rows, token_sum, _event_n = member_usage_log_rows(
        db, user.id, usd_krw_rate=usd_krw, limit=100
    )
    return {
        "ai_usage_total_usd": format_usd_from_micro(total_micro),
        "ai_usage_total_krw": format_krw_from_micro(total_micro, usd_krw),
        "ai_usage_total_krw_int": usage_krw_int,
        "ai_usage_event_count": usage_agg.get("event_count", 0),
        "ai_usage_total_tokens_display": format_token_count(token_sum) if token_sum > 0 else "—",
        "ai_usage_log_rows": log_rows,
        "ai_usage_stage_rows": stage_rows,
        "usd_krw_rate": usd_krw,
    }


@router.get("/account/ai-credits", response_class=HTMLResponse)
def account_ai_credits_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={quote(_AI_CREDITS_PATH)}", status_code=302)
    try:
        sync_user_portone_transactions(
            db,
            int(user.id),
            purpose=PURPOSE_AI_WALLET_TOPUP,
            limit=10,
        )
        db.refresh(user)
    except Exception:
        pass
    settings = _load_bank_settings(db)
    err = (request.query_params.get("err") or "").strip()
    ok_param = (request.query_params.get("ok") or "").strip()
    ok = ok_param in ("1", "portone")
    ctx = _usage_context(db, user)
    payment_usd = user_prefers_usd_payments(user)
    paypal_channel = bool(portone_paypal_channel_key())
    bal_krw = member_wallet_balance_display_krw(user)
    return templates.TemplateResponse(
        request,
        "account_ai_credits.html",
        {
            "user": user,
            "settings": settings,
            "payment_usd": payment_usd,
            "wallet_balance_krw": bal_krw,
            "wallet_balance_usd": wallet_balance_usd_display(bal_krw, ctx["usd_krw_rate"])
            if payment_usd
            else None,
            "min_topup_krw": min_topup_krw(db),
            "min_topup_usd_cents": min_topup_usd_cents(db),
            "topup_history_rows": build_wallet_topup_history_rows(
                db,
                user.id,
                usd_krw_rate=ctx["usd_krw_rate"],
                current_wallet_krw=bal_krw,
                display_usd=payment_usd,
                limit=50,
            ),
            "pending_claim": user_pending_claim(db, user.id),
            "billing_err": err,
            "billing_ok": ok,
            "portone_ready": portone_checkout_ready() and (not payment_usd or paypal_channel),
            "portone_paypal_configured": paypal_channel,
            **ctx,
        },
    )


@router.post("/account/ai-credits/pay-portone")
def account_ai_credits_pay_portone(
    request: Request,
    db: Session = Depends(get_db),
    amount_minor: str = Form(""),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={quote(_AI_CREDITS_PATH)}", status_code=302)
    if not portone_checkout_ready():
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=portone_unconfigured", status_code=303)
    payment_usd = user_prefers_usd_payments(user)
    if payment_usd and not portone_paypal_channel_key():
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=paypal_unconfigured", status_code=303)
    return_url = f"{_AI_CREDITS_PATH}#topup-form"
    if payment_usd:
        usd_cents = parse_usd_input_to_cents(amount_minor)
        if usd_cents is None:
            return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=invalid_amount", status_code=303)
        if usd_cents < min_topup_usd_cents(db):
            return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=amount_too_low", status_code=303)
        txn = create_pending_transaction(
            db,
            user,
            purpose=PURPOSE_AI_WALLET_TOPUP,
            purpose_ref_id=int(user.id),
            amount_krw=usd_cents,
            return_url=return_url,
            cancel_url=f"{_AI_CREDITS_PATH}?err=portone_cancelled#topup-form",
            currency="USD",
        )
    else:
        try:
            amt = int((amount_minor or "").replace(",", "").strip())
        except ValueError:
            return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=invalid_amount", status_code=303)
        if amt < min_topup_krw(db):
            return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=amount_too_low", status_code=303)
        txn = create_pending_transaction(
            db,
            user,
            purpose=PURPOSE_AI_WALLET_TOPUP,
            purpose_ref_id=int(user.id),
            amount_krw=amt,
            return_url=return_url,
            cancel_url=f"{_AI_CREDITS_PATH}?err=portone_cancelled#topup-form",
            currency="KRW",
        )
    if not txn:
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=portone_error", status_code=303)
    pid = (txn.payment_id or "").strip()
    txn.return_url = f"{_AI_CREDITS_PATH}?portone_sync={quote(pid)}#topup-form"
    db.add(txn)
    db.commit()
    return RedirectResponse(url=f"/payments/portone/checkout/{int(txn.id)}", status_code=303)


@router.post("/account/ai-credits/claim")
def account_ai_credits_claim_post(
    request: Request,
    db: Session = Depends(get_db),
    amount_minor: str = Form(""),
    depositor_name: str = Form(""),
    transfer_date: str = Form(""),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={quote(_AI_CREDITS_PATH)}", status_code=302)
    try:
        amt = int((amount_minor or "").replace(",", "").strip())
    except ValueError:
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err=invalid_amount", status_code=303)
    row, err = create_wallet_topup_claim(
        db,
        user,
        amount_minor=amt,
        depositor_name=depositor_name,
        transfer_date=_parse_transfer_date(transfer_date),
    )
    if err:
        if str(err).startswith(f"{ERR_AMOUNT_MISMATCH}:"):
            return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err={ERR_AMOUNT_MISMATCH}", status_code=303)
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err={quote(str(err))}", status_code=303)
    return RedirectResponse(url=f"{_AI_CREDITS_PATH}?ok=1#topup-form", status_code=303)


@router.post("/account/ai-credits/claim/{claim_id}/cancel")
def account_ai_credits_claim_cancel(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={quote(_AI_CREDITS_PATH)}", status_code=302)
    err = cancel_payment_claim(db, user, claim_id)
    if err:
        return RedirectResponse(url=f"{_AI_CREDITS_PATH}?err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{_AI_CREDITS_PATH}?ok=1", status_code=303)
