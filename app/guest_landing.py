"""비로그인 홈(게스트 랜딩) — /ia 시안을 / 에서 제공."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from .site_markdown_html import site_markdown_to_html
from .site_settings_locale import enrich_site_settings
from .social_oauth import google_oauth_configured
from .templates_config import templates

GUEST_DETAIL_SETTING_KEYS = (
    "ia_guest_detail_enabled",
    "ia_guest_detail_md_ko",
    "ia_guest_detail_md_en",
)

IA_LANDING_DEPLOY_MARKER = "20260617-guest-home-r1"


def _guest_detail_settings(db: Session) -> dict[str, str]:
    from . import models

    rows = (
        db.query(models.SiteSettings)
        .filter(models.SiteSettings.key.in_(GUEST_DETAIL_SETTING_KEYS))
        .all()
    )
    raw = {s.key: s.value for s in rows}
    return enrich_site_settings(db, raw, scope=None, auto_translate=False)


def guest_detail_html(db: Session) -> tuple[bool, str, str]:
    """Return (show_section, html_ko, html_en)."""
    settings = _guest_detail_settings(db)
    enabled = (settings.get("ia_guest_detail_enabled") or "1").strip() != "0"
    ko_md = (settings.get("ia_guest_detail_md_ko") or "").strip()
    en_md = (settings.get("ia_guest_detail_md_en") or "").strip() or ko_md
    if not enabled or not (ko_md or en_md):
        return False, "", ""
    return True, site_markdown_to_html(ko_md), site_markdown_to_html(en_md)


def guest_landing_context(
    request: Request,
    db: Session,
    *,
    oauth_error: str = "",
    oauth_next: str = "/",
) -> dict:
    show_detail, detail_html_ko, detail_html_en = guest_detail_html(db)
    return {
        "request": request,
        "user": None,
        "guest_landing_page": True,
        "google_oauth_enabled": google_oauth_configured(),
        "oauth_next": oauth_next,
        "oauth_error": (oauth_error or "").strip(),
        "guest_detail_visible": show_detail,
        "guest_detail_html_ko": detail_html_ko,
        "guest_detail_html_en": detail_html_en,
    }


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
