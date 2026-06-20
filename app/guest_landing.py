"""비로그인 홈(게스트 랜딩) — /ia 시안을 / 에서 제공."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from .service_landing_intro import service_landing_intro_context
from .social_oauth import google_oauth_configured
from .templates_config import templates

IA_LANDING_DEPLOY_MARKER = "20260529-guest-home-r3"


def guest_landing_context(
    request: Request,
    db: Session,
    *,
    oauth_error: str = "",
    oauth_next: str = "/",
) -> dict:
    ctx = {
        "request": request,
        "user": None,
        "guest_landing_page": True,
        "google_oauth_enabled": google_oauth_configured(),
        "oauth_next": oauth_next,
        "oauth_error": (oauth_error or "").strip(),
    }
    ctx.update(service_landing_intro_context(db))
    return ctx


def render_guest_landing(
    request: Request,
    db: Session,
    *,
    oauth_error: str = "",
    oauth_next: str = "/",
):
    return templates.TemplateResponse(
        request,
        "ia/landing.html",
        guest_landing_context(
            request,
            db,
            oauth_error=oauth_error,
            oauth_next=oauth_next,
        ),
    )
