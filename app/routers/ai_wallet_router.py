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
    format_usd_from_micro,
)
from ..ai_wallet import MIN_TOPUP_KRW, claim_plan_label_en, claim_plan_label_ko, wallet_balance_krw
from ..bank_transfer_settings import BANK_TRANSFER_SETTING_KEYS
from ..database import get_db
from ..payment_claim_messages import ERR_AMOUNT_MISMATCH
from ..payment_claim_service import (
    cancel_payment_claim,
    claim_status_label_en,
    claim_status_label_ko,
    claims_for_user,
    create_wallet_topup_claim,
    user_pending_claim,
)
from ..subscription_catalog import METRIC_LABEL_EN, METRIC_LABEL_KO, METRIC_ORDER
from ..subscription_quota import utc_year_month
from ..templates_config import templates

router = APIRouter(tags=["ai-wallet"])

_AI_CREDITS_PATH = "/account/ai-credits"


def _load_bank_settings(db: Session) -> dict[str, str]:
    keys = set(BANK_TRANSFER_SETTING_KEYS)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).filter(models.SiteSettings.key.in_(keys)).all()}
    return {k: (raw.get(k) or "").strip() for k in BANK_TRANSFER_SETTING_KEYS}


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
                "pct": round(pct, 1),
            }
        )
    ym = utc_year_month()
    usage_rows = (
        db.query(models.SubscriptionUsageMonthly)
        .filter(
            models.SubscriptionUsageMonthly.user_id == user.id,
            models.SubscriptionUsageMonthly.year_month == ym,
        )
        .all()
    )
    usage_map = {r.metric_key: int(r.used) for r in usage_rows}
    return {
        "usage_year_month": ym,
        "usage_map": usage_map,
        "metric_order": METRIC_ORDER,
        "metric_label_ko": METRIC_LABEL_KO,
        "metric_label_en": METRIC_LABEL_EN,
        "ai_usage_total_usd": format_usd_from_micro(total_micro),
        "ai_usage_total_krw": format_krw_from_micro(total_micro, usd_krw),
        "ai_usage_event_count": usage_agg.get("event_count", 0),
        "ai_usage_stage_rows": stage_rows,
        "usd_krw_rate": usd_krw,
    }


@router.get("/account/ai-credits", response_class=HTMLResponse)
def account_ai_credits_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={quote(_AI_CREDITS_PATH)}", status_code=302)
    settings = _load_bank_settings(db)
    err = (request.query_params.get("err") or "").strip()
    ok = request.query_params.get("ok") == "1"
    ctx = _usage_context(db, user)
    return templates.TemplateResponse(
        request,
        "account_ai_credits.html",
        {
            "user": user,
            "settings": settings,
            "wallet_balance_krw": wallet_balance_krw(user),
            "min_topup_krw": MIN_TOPUP_KRW,
            "claims": claims_for_user(db, user.id, limit=30),
            "pending_claim": user_pending_claim(db, user.id),
            "billing_err": err,
            "billing_ok": ok,
            "claim_status_label_ko": claim_status_label_ko,
            "claim_status_label_en": claim_status_label_en,
            "claim_plan_label_ko": claim_plan_label_ko,
            "claim_plan_label_en": claim_plan_label_en,
            **ctx,
        },
    )


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
    err, _row = create_wallet_topup_claim(
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
