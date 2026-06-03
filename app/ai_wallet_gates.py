"""AI 크레딧 — HTTP·UI용 잔액 검사·리다이렉트 (관리자 제외)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import Request
from sqlalchemy.orm import Session

WALLET_ERR_INSUFFICIENT = "wallet_insufficient"


def wallet_flash_from_query(request: Request) -> dict[str, str] | None:
    w = (request.query_params.get("wallet_err") or "").strip()
    if w == WALLET_ERR_INSUFFICIENT:
        return {"kind": "danger", "i18n": "wallet.insufficientFlash"}
    return None


def url_append_query(url: str, key: str, value: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{quote(key)}={quote(value)}"


def wallet_insufficient_url(url: str) -> str:
    return url_append_query(url, "wallet_err", WALLET_ERR_INSUFFICIENT)


def wallet_insufficient_message(*, lang: str = "ko") -> str:
    if (lang or "").strip().lower() == "en":
        return (
            "Insufficient AI credits. Top up on the AI credits page, then try again."
        )
    return (
        "AI 크레딧 잔액이 부족합니다. "
        "「사용량 · 충전」에서 충전한 뒤 다시 시도해 주세요."
    )


def wallet_preflight_for_ai(db: Session, user: Any | None, *, stage: str) -> str | None:
    from .ai_usage_billing import wallet_preflight_for_ai_stage

    return wallet_preflight_for_ai_stage(db, user, stage=stage)


def wallet_preflight_for_user_id(db: Session, user_id: int, *, stage: str) -> str | None:
    from . import models

    u = db.query(models.User).filter(models.User.id == int(user_id)).first()
    return wallet_preflight_for_ai(db, u, stage=stage)
