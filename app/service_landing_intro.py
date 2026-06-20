"""Service menu landing intro HTML — shared by logged-in landings and guest home."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .menu_landing import (
    DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO,
    DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO,
)
from .proposal_markdown_html import markdown_to_html
from .rfp_landing import DEFAULT_SERVICE_ABAP_INTRO_MD_KO
from .site_settings_locale import (
    enrich_site_settings,
    load_service_abap_settings_dict,
    load_service_analysis_settings_dict,
    load_service_integration_settings_dict,
)


def _intro_html_pair(
    raw: dict[str, str],
    *,
    ko_key: str,
    en_key: str,
    default_ko: str,
    db: Session,
) -> tuple[str, str]:
    settings = dict(raw)
    settings[ko_key] = (settings.get(ko_key) or "").strip() or default_ko
    enriched = enrich_site_settings(db, settings, scope="service")
    md_ko = enriched[ko_key]
    md_en = (enriched.get(en_key) or "").strip() or md_ko
    return markdown_to_html(md_ko), markdown_to_html(md_en)


def service_landing_intro_context(db: Session) -> dict[str, str]:
    """KO/EN intro HTML for 신규개발 · 분석·개선 · 연동개발 landing headers."""
    abap_ko, abap_en = _intro_html_pair(
        load_service_abap_settings_dict(db),
        ko_key="service_abap_intro_md_ko",
        en_key="service_abap_intro_md_en",
        default_ko=DEFAULT_SERVICE_ABAP_INTRO_MD_KO,
        db=db,
    )
    analysis_ko, analysis_en = _intro_html_pair(
        load_service_analysis_settings_dict(db),
        ko_key="service_analysis_intro_md_ko",
        en_key="service_analysis_intro_md_en",
        default_ko=DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO,
        db=db,
    )
    integration_ko, integration_en = _intro_html_pair(
        load_service_integration_settings_dict(db),
        ko_key="service_integration_intro_md_ko",
        en_key="service_integration_intro_md_en",
        default_ko=DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO,
        db=db,
    )
    return {
        "service_abap_intro_html_ko": abap_ko,
        "service_abap_intro_html_en": abap_en,
        "service_analysis_intro_html_ko": analysis_ko,
        "service_analysis_intro_html_en": analysis_en,
        "service_integration_intro_html_ko": integration_ko,
        "service_integration_intro_html_en": integration_en,
    }
