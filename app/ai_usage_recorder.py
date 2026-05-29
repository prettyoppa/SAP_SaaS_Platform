"""추정 AI 이용 비용 원장 — CrewAI kickoff·Gemini 직접 호출 후 기록."""

from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from . import models
from .database import SessionLocal
from .gemini_model import get_gemini_model_id

_log = logging.getLogger(__name__)

# stage → 대략적 1회 호출 비용 (micro USD). API usage 없을 때 fallback.
STAGE_LABEL_KO: dict[str, str] = {
    "interview": "인터뷰",
    "proposal": "제안서",
    "fs": "기능명세(FS)",
    "delivered_code": "납품 코드",
    "ai_inquiry": "AI 문의",
    "codelib": "코드 라이브러리",
    "integration_deliverable": "연동 산출물",
    "kb_gallery": "지식갤러리",
    "delivery_workspace_fix": "SE38 납품 작업실",
    "other": "기타",
}

STAGE_LABEL_EN: dict[str, str] = {
    "interview": "Interview",
    "proposal": "Proposal",
    "fs": "Functional spec (FS)",
    "delivered_code": "Delivered code",
    "ai_inquiry": "AI Q&A",
    "codelib": "Code library",
    "integration_deliverable": "Integration deliverable",
    "kb_gallery": "Knowledge gallery",
    "delivery_workspace_fix": "SE38 Delivery Studio",
    "other": "Other",
}

FALLBACK_COST_USD_MICRO: dict[str, int] = {
    "interview": 50_000,
    "proposal": 90_000,
    "fs": 120_000,
    "delivered_code": 180_000,
    "ai_inquiry": 25_000,
    "codelib": 40_000,
    "integration_deliverable": 100_000,
    "kb_gallery": 55_000,
    "delivery_workspace_fix": 35_000,
    "other": 35_000,
}

# model_id substring → (input per 1M tokens USD, output per 1M tokens USD) — 운영 시 Admin rate로 대체 가능
_MODEL_USD_PER_M: dict[str, tuple[float, float]] = {
    "gemini-2.5": (0.30, 2.50),
    "gemini-2.0": (0.10, 0.40),
    "gemini-1.5": (0.075, 0.30),
    "default": (0.15, 0.60),
}


@dataclass(frozen=True)
class AiUsageContext:
    user_id: int
    request_kind: str = "system"
    request_id: int | None = None


_ctx: contextvars.ContextVar[AiUsageContext | None] = contextvars.ContextVar(
    "ai_usage_ctx", default=None
)


def get_ai_usage_context() -> AiUsageContext | None:
    return _ctx.get()


@contextmanager
def ai_usage_scope(ctx: AiUsageContext) -> Iterator[None]:
    token = _ctx.set(ctx)
    try:
        yield
    finally:
        _ctx.reset(token)


def _model_rates(model_id: str) -> tuple[float, float]:
    mid = (model_id or "").lower()
    for key, rates in _MODEL_USD_PER_M.items():
        if key != "default" and key in mid:
            return rates
    return _MODEL_USD_PER_M["default"]


def estimate_cost_usd_micro(
    *,
    model_id: str,
    input_tokens: int | None,
    output_tokens: int | None,
    stage: str,
) -> tuple[int, str]:
    """Returns (micro_usd, cost_source)."""
    if input_tokens is not None or output_tokens is not None:
        inp = max(0, int(input_tokens or 0))
        out = max(0, int(output_tokens or 0))
        pin, pout = _model_rates(model_id)
        usd = (inp * pin + out * pout) / 1_000_000.0
        return max(1, int(usd * 1_000_000)), "api_usage"
    fb = FALLBACK_COST_USD_MICRO.get(stage) or FALLBACK_COST_USD_MICRO["other"]
    return fb, "fallback_avg"


def _extract_usage_from_kickoff_result(result: Any) -> tuple[int | None, int | None, int | None]:
    for attr in ("token_usage", "usage", "usage_metadata"):
        u = getattr(result, attr, None)
        if u is None:
            continue
        if isinstance(u, dict):
            inp = u.get("prompt_tokens") or u.get("input_tokens")
            out = u.get("completion_tokens") or u.get("output_tokens")
            tot = u.get("total_tokens")
        else:
            inp = getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", None)
            out = getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", None)
            tot = getattr(u, "total_tokens", None)
        return (
            int(inp) if inp is not None else None,
            int(out) if out is not None else None,
            int(tot) if tot is not None else None,
        )
    return None, None, None


def log_ai_usage_event(
    *,
    user_id: int,
    stage: str,
    request_kind: str = "system",
    request_id: int | None = None,
    agent_key: str | None = None,
    model_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_source: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    ctx = get_ai_usage_context()
    if ctx:
        user_id = ctx.user_id
        request_kind = ctx.request_kind or request_kind
        if ctx.request_id is not None:
            request_id = ctx.request_id
    mid = (model_id or get_gemini_model_id() or "").strip()
    raw_micro, src = estimate_cost_usd_micro(
        model_id=mid,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stage=stage,
    )
    if cost_source:
        src = cost_source
    tot = None
    if input_tokens is not None or output_tokens is not None:
        tot = (input_tokens or 0) + (output_tokens or 0)
    db = SessionLocal()
    try:
        from .ai_usage_pricing import billable_usd_micro

        micro = billable_usd_micro(db, raw_micro)
        if idempotency_key:
            exists = (
                db.query(models.AiUsageEvent)
                .filter(models.AiUsageEvent.idempotency_key == idempotency_key)
                .first()
            )
            if exists:
                return
        db.add(
            models.AiUsageEvent(
                user_id=int(user_id),
                request_kind=(request_kind or "system")[:32],
                request_id=request_id,
                stage=(stage or "other")[:32],
                agent_key=(agent_key or "")[:64] or None,
                model_id=mid[:128],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=tot,
                estimated_cost_usd_micro=micro,
                cost_source=src[:20],
                idempotency_key=idempotency_key,
            )
        )
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
        if user:
            from .ai_wallet import debit_wallet_for_usage_micro

            debit_wallet_for_usage_micro(db, user, micro)
        db.commit()
    except Exception:
        _log.exception("ai_usage_event write failed")
        db.rollback()
    finally:
        db.close()


def logged_crew_kickoff(crew: Any, *, stage: str, agent_key: str | None = None) -> Any:
    """Crew.kickoff() 래퍼 — 컨텍스트가 있을 때만 원장 기록."""
    result = crew.kickoff()
    ctx = get_ai_usage_context()
    if ctx:
        inp, out, _ = _extract_usage_from_kickoff_result(result)
        log_ai_usage_event(
            user_id=ctx.user_id,
            stage=stage,
            request_kind=ctx.request_kind,
            request_id=ctx.request_id,
            agent_key=agent_key,
            input_tokens=inp,
            output_tokens=out,
            idempotency_key=f"crew-{uuid.uuid4().hex}",
        )
    return result


def log_gemini_generate_content(
    response: Any,
    *,
    stage: str,
    agent_key: str | None = "gemini",
    user_id: int | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> None:
    ctx = get_ai_usage_context()
    uid = user_id if user_id is not None else (ctx.user_id if ctx else None)
    if not uid:
        return
    rk = request_kind if request_kind is not None else (ctx.request_kind if ctx else "system")
    rid = request_id if request_id is not None else (ctx.request_id if ctx else None)
    inp = out = None
    meta = getattr(response, "usage_metadata", None)
    if meta:
        inp = getattr(meta, "prompt_token_count", None)
        out = getattr(meta, "candidates_token_count", None)
    log_ai_usage_event(
        user_id=int(uid),
        stage=stage,
        request_kind=rk,
        request_id=rid,
        agent_key=agent_key,
        input_tokens=int(inp) if inp is not None else None,
        output_tokens=int(out) if out is not None else None,
        idempotency_key=f"gem-{uuid.uuid4().hex}",
    )


def aggregate_usage_for_user(
    db,
    user_id: int,
    *,
    since=None,
    until=None,
) -> dict[str, Any]:
    """Admin 대시보드용 집계."""
    q = db.query(models.AiUsageEvent).filter(models.AiUsageEvent.user_id == int(user_id))
    if since is not None:
        q = q.filter(models.AiUsageEvent.created_at >= since)
    if until is not None:
        q = q.filter(models.AiUsageEvent.created_at <= until)
    rows = q.order_by(models.AiUsageEvent.created_at.asc()).all()
    total_micro = sum(int(r.estimated_cost_usd_micro or 0) for r in rows)
    by_stage: dict[str, int] = {}
    for r in rows:
        st = (r.stage or "other").strip()
        by_stage[st] = by_stage.get(st, 0) + int(r.estimated_cost_usd_micro or 0)
    return {
        "event_count": len(rows),
        "total_usd_micro": total_micro,
        "by_stage_micro": by_stage,
        "rows": rows[-200:],
    }


def format_usd_from_micro(micro: int) -> str:
    usd = micro / 1_000_000.0
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.2f}"


def format_krw_from_micro(micro: int, usd_krw_rate: float) -> str:
    krw = (micro / 1_000_000.0) * usd_krw_rate
    return f"₩{krw:,.0f}"


def format_token_count(n: int | None) -> str:
    if n is None or n <= 0:
        return "—"
    v = int(n)
    if v >= 1_000_000:
        s = f"{v / 1_000_000:.1f}"
        if s.endswith(".0"):
            s = s[:-2]
        return f"{s}M"
    if v >= 1000:
        s = f"{v / 1000:.1f}"
        if s.endswith(".0"):
            s = s[:-2]
        return f"{s}K"
    return f"{v:,}"


def format_tokens_cell(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    cost_source: str,
) -> str:
    if (cost_source or "").strip() != "api_usage":
        return "—"
    if total_tokens is not None and total_tokens > 0:
        return format_token_count(total_tokens)
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    if inp <= 0 and out <= 0:
        return "—"
    if inp > 0 and out > 0:
        return f"{format_token_count(inp)} in / {format_token_count(out)} out"
    return format_token_count(inp or out)


def member_usage_log_rows(
    db,
    user_id: int,
    *,
    usd_krw_rate: float,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], int, int]:
    """회원 화면용 호출 로그(최신순) + (표시 가능 토큰 합, 이벤트 수)."""
    from .ai_wallet import krw_from_usage_usd_micro

    agg = aggregate_usage_for_user(db, int(user_id))
    events = list(reversed(list(agg.get("rows") or [])))[: max(1, int(limit))]
    rows: list[dict[str, Any]] = []
    token_sum = 0
    for ev in events:
        st = (ev.stage or "other").strip()
        src = (ev.cost_source or "").strip()
        tot_tok = ev.total_tokens
        if tot_tok is None and (ev.input_tokens or ev.output_tokens):
            tot_tok = int(ev.input_tokens or 0) + int(ev.output_tokens or 0)
        if src == "api_usage" and tot_tok and tot_tok > 0:
            token_sum += int(tot_tok)
        micro = int(ev.estimated_cost_usd_micro or 0)
        rows.append(
            {
                "event": ev,
                "created_at": ev.created_at,
                "label_ko": STAGE_LABEL_KO.get(st, st),
                "label_en": STAGE_LABEL_EN.get(st, st),
                "model_id": (ev.model_id or "").strip() or "—",
                "tokens_display": format_tokens_cell(
                    input_tokens=ev.input_tokens,
                    output_tokens=ev.output_tokens,
                    total_tokens=tot_tok,
                    cost_source=src,
                ),
                "is_estimate": src != "api_usage",
                "krw_int": krw_from_usage_usd_micro(micro, usd_krw_rate),
                "usd": format_usd_from_micro(micro),
            }
        )
    return rows, token_sum, int(agg.get("event_count") or 0)
