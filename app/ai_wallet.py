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
    """폼 입력(달러, 소수 2자리, 천단위 콤마 허용) → USD cents."""
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


def member_wallet_balance_display_krw(user) -> int:
    """회원·컨설턴트 화면 표시용 — 음수 잔액은 0으로."""
    bal = wallet_balance_krw(user)
    try:
        from .ai_usage_billing import user_skips_wallet

        if user_skips_wallet(user):
            return bal
    except Exception:
        pass
    return max(0, bal)


def apply_wallet_credit(user, amount_krw: int) -> int:
    """원화 잔액에 amount를 더하고 갱신된 잔액을 반환."""
    new_bal = wallet_balance_krw(user) + int(amount_krw)
    user.ai_wallet_balance_krw = new_bal
    return new_bal


def apply_wallet_debit(user, amount_krw: int, *, allow_negative: bool = False) -> int:
    """충전 취소·거절·AI 사용 추정 비용 차감. 일반 회원은 0 미만 불가."""
    amount = max(0, int(amount_krw))
    if amount <= 0:
        return wallet_balance_krw(user)
    bal = wallet_balance_krw(user)
    skip_floor = allow_negative
    if not skip_floor:
        try:
            from .ai_usage_billing import user_skips_wallet

            skip_floor = user_skips_wallet(user)
        except Exception:
            skip_floor = False
    if skip_floor:
        new_bal = bal - amount
    else:
        amount = min(amount, max(0, bal))
        new_bal = max(0, bal - amount)
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
    """AI 사용 원장(micro USD)에 대응하는 원화를 지갑에서 차감. 실제 차감액 반환."""
    if user is None:
        return 0
    try:
        from .ai_usage_billing import user_skips_wallet

        if user_skips_wallet(user):
            return 0
    except Exception:
        pass
    krw = krw_from_usage_usd_micro(int(usd_micro), usd_krw_rate_from_db(db))
    if krw <= 0:
        return 0
    bal = wallet_balance_krw(user)
    debit_amt = min(krw, max(0, bal))
    if debit_amt > 0:
        apply_wallet_debit(user, debit_amt)
    return debit_amt


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


def usd_cents_from_usd_micro(micro: int) -> int:
    """USD micro (1e-6 USD) → USD cents."""
    return max(0, int(round(int(micro) / 10_000.0)))


def krw_to_usd_cents(krw: int, usd_krw_rate: float) -> int:
    """KRW won → USD cents at platform rate (display only)."""
    rate = float(usd_krw_rate or 1350.0)
    if rate <= 0:
        rate = 1350.0
    return max(0, int(round((int(krw) / rate) * 100)))


def wallet_balance_usd_display(wallet_krw: int, usd_krw_rate: float) -> float:
    rate = float(usd_krw_rate or 1350.0)
    if rate <= 0:
        rate = 1350.0
    return round(int(wallet_krw) / rate, 2)


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


def portone_txn_credit_krw(txn, usd_krw_rate: float) -> int:
    """PortOne paid txn → wallet credit in KRW (USD cents converted at platform rate)."""
    amt = int(getattr(txn, "amount_minor", 0) or 0)
    if (getattr(txn, "currency", None) or "KRW").strip().upper() == "USD":
        return max(1, int(round((amt / 100.0) * float(usd_krw_rate or 1350.0))))
    return amt


def display_confirmed_amount_minor(claim) -> int:
    status = (getattr(claim, "status", None) or "").strip()
    if status != "confirmed":
        return 0
    raw = getattr(claim, "confirmed_amount_minor", None)
    if raw is not None:
        return max(0, int(raw))
    return int(getattr(claim, "amount_minor", 0) or 0)


def aggregate_topup_krw_totals_for_users(
    db,
    user_ids: list[int],
    *,
    usd_krw_rate: float,
) -> dict[int, int]:
    """회원 목록 등 — user_id별 누적 충전(KRW). 계좌이체 + PortOne 카드."""
    ids = [int(x) for x in user_ids if x is not None]
    if not ids:
        return {}
    from . import models
    from .payment_purpose import PURPOSE_AI_WALLET_TOPUP

    out = {uid: 0 for uid in ids}
    claims = (
        db.query(models.PaymentClaim)
        .filter(
            models.PaymentClaim.user_id.in_(ids),
            models.PaymentClaim.plan_code == WALLET_TOPUP_PLAN_CODE,
        )
        .all()
    )
    for claim in claims:
        uid = int(claim.user_id)
        out[uid] = out.get(uid, 0) + topup_contribution_krw(claim)

    txns = (
        db.query(models.PaymentTransaction)
        .filter(
            models.PaymentTransaction.user_id.in_(ids),
            models.PaymentTransaction.purpose == PURPOSE_AI_WALLET_TOPUP,
            models.PaymentTransaction.status == "paid",
        )
        .all()
    )
    rate = float(usd_krw_rate or 1350.0)
    for txn in txns:
        uid = int(txn.user_id)
        out[uid] = out.get(uid, 0) + portone_txn_credit_krw(txn, rate)
    return out


def build_wallet_topup_history_rows(
    db,
    user_id: int,
    *,
    usd_krw_rate: float,
    current_wallet_krw: int | None = None,
    display_usd: bool = False,
    limit: int = 50,
) -> list[dict]:
    """계좌이체 입금 신청(PaymentClaim) + PortOne 카드 충전(PaymentTransaction)을 시간순으로 합쳐 표시."""
    from bisect import bisect_right
    from datetime import datetime

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

    usage_times: list[datetime] = []
    usage_prefix_micro: list[int] = []
    usage_cum = 0
    for created_at, micro in (
        db.query(
            models.AiUsageEvent.created_at,
            models.AiUsageEvent.estimated_cost_usd_micro,
        )
        .filter(models.AiUsageEvent.user_id == int(user_id))
        .order_by(
            models.AiUsageEvent.created_at.asc(),
            models.AiUsageEvent.id.asc(),
        )
        .all()
    ):
        usage_times.append(created_at)
        usage_cum += int(micro or 0)
        usage_prefix_micro.append(usage_cum)

    def _usage_micro_until(ts: datetime) -> int:
        if not usage_times:
            return 0
        idx = bisect_right(usage_times, ts) - 1
        if idx < 0:
            return 0
        return usage_prefix_micro[idx]

    cum_topup_krw = 0
    cum_topup_usd_cents = 0
    built: list[dict] = []
    for ts, kind, obj in events:
        if kind == "bank_claim":
            claim = obj  # type: ignore[assignment]
            contrib_krw = topup_contribution_krw(claim)
            cum_topup_krw += contrib_krw
            until_ts = claim.created_at
            usage_micro = _usage_micro_until(until_ts)
            cum_usage_krw = krw_from_usage_usd_micro(usage_micro, usd_krw_rate)
            cum_usage_usd_cents = usd_cents_from_usd_micro(usage_micro)
            if display_usd:
                cum_topup_usd_cents += krw_to_usd_cents(contrib_krw, usd_krw_rate)
            row = {
                "source": "bank_claim",
                "claim": claim,
                "txn": None,
                "applied_at": claim.created_at,
                "amount_currency": "KRW",
                "amount_minor": int(claim.amount_minor),
                "confirmed_at": claim.confirmed_at if (claim.status or "") == "confirmed" else None,
                "confirmed_amount_minor": display_confirmed_amount_minor(claim),
                "cum_topup_krw": cum_topup_krw,
                "cum_usage_krw": cum_usage_krw,
                "balance_krw": cum_topup_krw - cum_usage_krw,
            }
        else:
            txn = obj  # type: ignore[assignment]
            amt = int(txn.amount_minor or 0)
            cur = (txn.currency or "KRW").strip().upper()
            credit_krw = portone_txn_credit_krw(txn, usd_krw_rate)
            cum_topup_krw += credit_krw
            usage_micro = _usage_micro_until(ts)
            cum_usage_krw = krw_from_usage_usd_micro(usage_micro, usd_krw_rate)
            cum_usage_usd_cents = usd_cents_from_usd_micro(usage_micro)
            paid_at = txn.paid_at or ts
            if display_usd:
                if cur == "USD":
                    cum_topup_usd_cents += amt
                else:
                    cum_topup_usd_cents += krw_to_usd_cents(credit_krw, usd_krw_rate)
            row = {
                "source": "portone_card",
                "claim": None,
                "txn": txn,
                "applied_at": paid_at,
                "amount_currency": cur,
                "amount_minor": amt,
                "confirmed_at": paid_at,
                "confirmed_amount_minor": amt,
                "credit_krw": credit_krw,
                "cum_topup_krw": cum_topup_krw,
                "cum_usage_krw": cum_usage_krw,
                "balance_krw": cum_topup_krw - cum_usage_krw,
            }
        if display_usd:
            row["cum_topup_usd_cents"] = cum_topup_usd_cents
            row["cum_usage_usd_cents"] = cum_usage_usd_cents
            row["balance_usd_cents"] = cum_topup_usd_cents - cum_usage_usd_cents
            if kind == "bank_claim":
                row["amount_display_usd_cents"] = krw_to_usd_cents(int(row["amount_minor"]), usd_krw_rate)
                conf_krw = int(row["confirmed_amount_minor"] or 0)
                row["confirmed_display_usd_cents"] = (
                    krw_to_usd_cents(conf_krw, usd_krw_rate) if row.get("confirmed_at") else 0
                )
            elif row.get("amount_currency") == "USD":
                row["amount_display_usd_cents"] = int(row["amount_minor"])
                row["confirmed_display_usd_cents"] = int(row["confirmed_amount_minor"] or 0)
            else:
                row["amount_display_usd_cents"] = krw_to_usd_cents(int(row["credit_krw"]), usd_krw_rate)
                row["confirmed_display_usd_cents"] = row["amount_display_usd_cents"]
        built.append(row)
    built.reverse()
    if built and current_wallet_krw is not None:
        built[0]["balance_krw"] = int(current_wallet_krw)
        if display_usd:
            built[0]["balance_usd_cents"] = krw_to_usd_cents(int(current_wallet_krw), usd_krw_rate)
    return built[:limit]
