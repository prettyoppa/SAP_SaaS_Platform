"""Fill missing English SiteSettings from Korean via auto-translation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .locale_auto_translate import get_or_translate_ko_to_en

# (korean_key, english_key, admin label for Gemini context)
LOCALE_SETTING_PAIRS: list[tuple[str, str, str]] = [
    ("home_hero_title", "home_hero_title_en", "Homepage hero title (max 3 lines, may include <br>)"),
    ("home_hero_subcopy", "home_hero_subcopy_en", "Homepage hero subcopy"),
    ("home_hero_desc", "home_hero_desc_en", "Homepage hero description"),
    ("home_guide_text_md", "home_guide_text_md_en", "Home getting-started guide (Markdown)"),
    ("home_tile_guide_title_ko", "home_tile_guide_title_en", "Home guide tile title"),
    ("home_tile_abap_title_ko", "home_tile_abap_title_en", "Home new development tile title"),
    ("home_tile_abap_desc_ko", "home_tile_abap_desc_en", "Home new development tile description"),
    ("home_tile_analysis_title_ko", "home_tile_analysis_title_en", "Home analysis tile title"),
    ("home_tile_analysis_desc_ko", "home_tile_analysis_desc_en", "Home analysis tile description"),
    ("home_tile_integration_title_ko", "home_tile_integration_title_en", "Home integration tile title"),
    ("home_tile_integration_desc_ko", "home_tile_integration_desc_en", "Home integration tile description"),
    ("service_abap_intro_md_ko", "service_abap_intro_md_en", "SAP ABAP service landing intro (Markdown)"),
    ("service_analysis_intro_md_ko", "service_analysis_intro_md_en", "ABAP analysis service landing intro (Markdown)"),
    ("service_integration_intro_md_ko", "service_integration_intro_md_en", "Integration service landing intro (Markdown)"),
    ("rfp_writing_tip", "rfp_writing_tip_en", "RFP writing tips box"),
    ("terms_markdown_ko", "terms_markdown_en", "Terms of service (Markdown)"),
    ("privacy_markdown_ko", "privacy_markdown_en", "Privacy policy (Markdown)"),
    ("user_guide_markdown_ko", "user_guide_markdown_en", "User guide (Markdown)"),
    ("subscription_plans_notice_md_ko", "subscription_plans_notice_md_en", "Subscription plans notice (Markdown)"),
    ("bank_transfer_notice_md_ko", "bank_transfer_notice_md_en", "Bank transfer notice KRW (Markdown)"),
    ("bank_transfer_notice_usd_md_ko", "bank_transfer_notice_usd_md_en", "Bank transfer notice USD (Markdown)"),
    ("bank_transfer_activation_sla_ko", "bank_transfer_activation_sla_en", "Bank transfer activation SLA text"),
    ("refund_policy_md_ko", "refund_policy_md_en", "Refund policy (Markdown)"),
]

def _pair_in_scope(ko_key: str, scope: str | None) -> bool:
    if scope is None:
        return True
    if scope == "home":
        return ko_key.startswith("home_")
    if scope == "service":
        return ko_key.startswith("service_")
    if scope == "rfp":
        return ko_key == "rfp_writing_tip"
    if scope == "legal":
        return ko_key.endswith("_markdown_ko")
    if scope == "billing":
        return ko_key.startswith(("subscription_", "bank_transfer_"))
    return True


def enrich_site_settings(
    db: Session,
    settings: dict[str, str],
    *,
    scope: str | None = None,
) -> dict[str, str]:
    """
    Copy settings and populate empty *_en (and virtual hero *_en) from Korean via cached Gemini.
    scope: None = all pairs; "home" = homepage-related only.
    """
    from .home_hero_defaults import (
        DEFAULT_HOME_HERO_DESC,
        DEFAULT_HOME_HERO_SUBCOPY,
        DEFAULT_HOME_HERO_TITLE,
    )

    hero_defaults = {
        "home_hero_title": DEFAULT_HOME_HERO_TITLE,
        "home_hero_subcopy": DEFAULT_HOME_HERO_SUBCOPY,
        "home_hero_desc": DEFAULT_HOME_HERO_DESC,
    }

    out = dict(settings)
    pairs = [p for p in LOCALE_SETTING_PAIRS if _pair_in_scope(p[0], scope)]

    for ko_key, en_key, purpose in pairs:
        ko = (out.get(ko_key) or "").strip()
        if not ko and ko_key in hero_defaults:
            ko = hero_defaults[ko_key]
        en = (out.get(en_key) or "").strip()
        if not ko or en:
            continue
        out[en_key] = get_or_translate_ko_to_en(db, ko, namespace=en_key, purpose=purpose)
    return out


def load_site_settings_enriched(db: Session, *, scope: str | None = None) -> dict[str, str]:
    from . import models

    raw = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    return enrich_site_settings(db, raw, scope=scope)


def resolve_ko_en(
    db: Session,
    settings: dict[str, str],
    ko_key: str,
    en_key: str,
    *,
    purpose: str,
) -> tuple[str, str]:
    """Return (ko, en) with auto-translated EN when admin EN field is empty."""
    ko = (settings.get(ko_key) or "").strip()
    en = (settings.get(en_key) or "").strip()
    if not en and ko:
        en = get_or_translate_ko_to_en(db, ko, namespace=en_key, purpose=purpose)
    return ko, en or ko


def effective_en(db: Session, settings: dict[str, str], ko_key: str, en_key: str, *, purpose: str) -> str:
    en = (settings.get(en_key) or "").strip()
    if en:
        return en
    ko = (settings.get(ko_key) or "").strip()
    if not ko:
        return ""
    return get_or_translate_ko_to_en(db, ko, namespace=en_key, purpose=purpose)
