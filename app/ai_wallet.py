"""AI 선불 잔액(원화) · 계좌이체 충전."""

from __future__ import annotations

WALLET_TOPUP_PLAN_CODE = "ai_wallet_topup"
DEFAULT_MIN_TOPUP_KRW = 30_000
MIN_TOPUP_KRW = DEFAULT_MIN_TOPUP_KRW  # backward-compatible alias
MIN_TOPUP_SETTING_KEY = "ai_wallet_min_topup_krw"


def min_topup_usd_cents(db) -> int:
    """USD 결제 최소 금액(센트) — ai_wallet_min_topup_krw ÷ 환율."""
    rate = usd_krw_rate_from_db(db)
    krw = min_topup_krw(db)
    return max(100, int(round((krw / rate) * 100)))


def parse_usd_input_to_cents(raw: str) -> int | None:
    """폼 입력(달러, 소수 2자리) → USD cents."""
    s = (raw or "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        dollars = float(s)
    except ValueError:
        return None
    if dollars <= 0:
        return None
    return max(1, int(round(dollars * 100)))


def min_topup_krw(db) -> int:
    from . import models

    row = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key == MIN_TOPUP_SETTING_KEY)
        .first()
    )
    raw = (row.value if row else "") or ""
    try:
        n = int(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return DEFAULT_MIN_TOPUP_KRW
    return n if n > 0 else DEFAULT_MIN_TOPUP_KRW


def wallet_balance_krw(user) -> int:
    return int(getattr(user, "ai_wallet_balance_krw", None) or 0)


def apply_wallet_credit(user, amount_krw: int) -> int:
    """원화 잔액에 amount를 더하고 갱신된 잔액을 반환."""
    new_bal = wallet_balance_krw(user) + int(amount_krw)
    user.ai_wallet_balance_krw = new_bal
    return new_bal


def apply_wallet_debit(user, amount_krw: int) -> int:
    """충전 취소·거절·AI 사용 추정 비용 차감."""
    new_bal = wallet_balance_krw(user) - int(amount_krw)
    user.ai_wallet_balance_krw = new_bal
    return new_bal


def usd_krw_rate_from_db(db) -> float:
    from . import models

    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == "usd_krw_rate").first()
    raw = (row.value if row else "") or "1350"
    try:
        return float(str(raw).strip().replace(",", ""))
    except ValueError:
        return 1350.0


def debit_wallet_for_usage_micro(db, user, usd_micro: int) -> int:
    """AI 사용 원장(micro USD)에 대응하는 원화를 지갑에서 차감. 차감액 반환."""
    krw = krw_from_usage_usd_micro(int(usd_micro), usd_krw_rate_from_db(db))
    if krw > 0 and user is not None:
        apply_wallet_debit(user, krw)
    return krw


def is_wallet_topup_plan_code(plan_code: str | None) -> bool:
    return (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE


def is_project_settlement_plan_code(plan_code: str | None) -> bool:
    from .project_settlement import PROJECT_SETTLEMENT_PLAN_CODE

    return (plan_code or "").strip() == PROJECT_SETTLEMENT_PLAN_CODE


def claim_plan_label_ko(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI 크레딧 충전"
    if is_project_settlement_plan_code(plan_code):
        return "납품 대금(프로젝트)"
    return plan_code or "—"


def claim_plan_label_en(plan_code: str) -> str:
    if (plan_code or "").strip() == WALLET_TOPUP_PLAN_CODE:
        return "AI credit top-up"
    if is_project_settlement_plan_code(plan_code):
        return "Project delivery payment"
    return plan_code or "—"


def krw_from_usage_usd_micro(micro: int, usd_krw_rate: float) -> int:
    return int(round((int(micro) / 1_000_000.0) * float(usd_krw_rate)))


def topup_contribution_krw(claim) -> int:
    """누적 충전 산정용: 취소·반려 0, 확인 시 확인금액, 대기 시 신청금액."""
    if (getattr(claim, "plan_code", None) or "").strip() != WALLET_TOPUP_PLAN_CODE:
        return 0
    status = (getattr(claim, "status", None) or "").strip()
    if status in ("cancelled", "rejected"):
        return 0
    if status == "confirmed":
        raw = getattr(claim, "confirmed_amount_minor", None)
        if raw is not None:
            return max(0, int(raw))
        return int(getattr(claim, "amount_minor", 0) or 0)
    return int(getattr(claim, "amount_minor", 0) or 0)


def display_confirmed_amount_minor(claim) -> int:
    status = (getattr(claim, "status", None) or "").strip()
    if status != "confirmed":
        return 0
    raw = getattr(claim, "confirmed_amount_minor", None)
    if raw is not None:
        return max(0, int(raw))
    return int(getattr(claim, "amount_minor", 0) or 0)


def build_wallet_topup_history_rows(
    db,
    user_id: int,
    *,
    usd_krw_rate: float,
    current_wallet_krw: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """계좌이체 입금 신청(PaymentClaim) + PortOne 카드 충전(PaymentTransaction)을 시간순으로 합쳐 표시."""
    from datetime import datetime

    from .ai_usage_recorder import aggregate_usage_for_user
    from . import models
    from .payment_purpose import PURPOSE_AI_WALLET_TOPUP

    claims = (
        db.query(models.PaymentClaim)
        .filter(
            models.PaymentClaim.user_id == int(user_id),
            models.PaymentClaim.plan_code == WALLET_TOPUP_PLAN_CODE,
        )
        .order_by(models.PaymentClaim.created_at.asc())
        .all()
    )
    txns = (
        db.query(models.PaymentTransaction)
        .filter(
            models.PaymentTransaction.user_id == int(user_id),
            models.PaymentTransaction.purpose == PURPOSE_AI_WALLET_TOPUP,
            models.PaymentTransaction.status == "paid",
        )
        .order_by(models.PaymentTransaction.paid_at.asc(), models.PaymentTransaction.id.asc())
        .all()
    )

    events: list[tuple[datetime, str, object]] = []
    for c in claims:
        events.append((c.created_at, "bank_claim", c))
    for t in txns:
        ts = t.paid_at or t.updated_at or t.created_at
        if ts is None:
            continue
        events.append((ts, "portone_card", t))
    events.sort(key=lambda x: (x[0], x[1], getattr(x[2], "id", 0)))

    cum_topup = 0
    built: list[dict] = []
    for ts, kind, obj in events:
        if kind == "bank_claim":
            claim = obj  # type: ignore[assignment]
            cum_topup += topup_contribution_krw(claim)
            until_ts = claim.created_at
            agg = aggregate_usage_for_user(db, int(user_id), until=until_ts)
            cum_usage = krw_from_usage_usd_micro(int(agg.get("total_usd_micro") or 0), usd_krw_rate)
            built.append(
                {
                    "source": "bank_claim",
                    "claim": claim,
                    "txn": None,
                    "applied_at": claim.created_at,
                    "amount_minor": int(claim.amount_minor),
                    "confirmed_at": claim.confirmed_at if (claim.status or "") == "confirmed" else None,
                    "confirmed_amount_minor": display_confirmed_amount_minor(claim),
                    "cum_topup_krw": cum_topup,
                    "cum_usage_krw": cum_usage,
                    "balance_krw": cum_topup - cum_usage,
                }
            )
        else:
            txn = obj  # type: ignore[assignment]
            amt = int(txn.amount_minor or 0)
            cum_topup += amt
            agg = aggregate_usage_for_user(db, int(user_id), until=ts)
            cum_usage = krw_from_usage_usd_micro(int(agg.get("total_usd_micro") or 0), usd_krw_rate)
            paid_at = txn.paid_at or ts
            built.append(
                {
                    "source": "portone_card",
                    "claim": None,
                    "txn": txn,
                    "applied_at": paid_at,
                    "amount_minor": amt,
                    "confirmed_at": paid_at,
                    "confirmed_amount_minor": amt,
                    "cum_topup_krw": cum_topup,
                    "cum_usage_krw": cum_usage,
                    "balance_krw": cum_topup - cum_usage,
                }
            )
    built.reverse()
    if built and current_wallet_krw is not None:
        built[0]["balance_krw"] = int(current_wallet_krw)
    return built[:limit]
