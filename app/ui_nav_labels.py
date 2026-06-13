"""Nav-aligned KO/EN labels (home tiles, menu landings, request console)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models

HOME_TILE_EN_NAV: dict[str, str] = {
    "home_tile_abap_title_en": "Develop",
    "home_tile_analysis_title_en": "Improve",
    "home_tile_integration_title_en": "Connect",
}

_LEGACY_HOME_TILE_EN: dict[str, frozenset[str]] = {
    "home_tile_abap_title_en": frozenset(
        {
            "New development",
            "New Development",
            "SAP ABAP development",
            "SAP ABAP Development",
            "New ABAP Development",
            "New ABAP development",
        }
    ),
    "home_tile_analysis_title_en": frozenset(
        {
            "Analyze · improve",
            "Analyze · Improve",
            "Analyze & improve",
            "Analyze & Improvement",
            "ABAP analysis · improvement",
            "SAP ABAP Analysis & Improvement",
        }
    ),
    "home_tile_integration_title_en": frozenset(
        {
            "Integration",
            "Integration development",
            "SAP Integration Dev",
            "SAP integration development",
            "SAP-Connected Development",
            "External",
            "Connect development",
        }
    ),
}

KIND_LABELS_KO: dict[str, str] = {
    "all": "전체",
    "abap": "신규개발",
    "analysis": "분석개선",
    "integration": "연동개발",
    "offer": "오퍼",
    "matching": "매칭",
}

KIND_LABELS_EN: dict[str, str] = {
    "all": "All",
    "abap": "Develop",
    "analysis": "Improve",
    "integration": "Connect",
    "offer": "Offers",
    "matching": "Matching",
}

ROW_KIND_EN: dict[str, str] = {
    "abap": "Develop",
    "rfp": "Develop",
    "analysis": "Improve",
    "integration": "Connect",
}

BUCKET_LABEL_EN: dict[str, str] = {
    "all": "All",
    "delivery": "Delivered",
    "proposal": "Proposal",
    "analysis": "Analysis",
    "in_progress": "In progress",
    "draft": "Draft",
}

I18N_NAV_CANONICAL_EN: dict[str, str] = {
    "nav.menuRequestConsole": "Console",
    "nav.menuNewDevelopment": "Develop",
    "nav.menuAnalysisImprove": "Improve",
    "nav.menuIntegration": "Connect",
    "svcAbap.pageTitle": "Develop",
    "analysis.pageTitle": "Improve",
    "integration.pageTitle": "Connect",
}


def row_kind_en(kind: str) -> str:
    return ROW_KIND_EN.get((kind or "").strip(), kind or "")


def migrate_home_tile_en_nav_labels(db: Session) -> int:
    """Align stored home-tile EN titles with top-nav short labels."""
    n = 0
    for key, canonical in HOME_TILE_EN_NAV.items():
        row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
        if not row:
            continue
        cur = (row.value or "").strip()
        legacy = _LEGACY_HOME_TILE_EN.get(key, frozenset())
        if cur == canonical:
            continue
        if cur in legacy or cur != canonical:
            row.value = canonical
            n += 1
    if n:
        db.commit()
    return n


def migrate_i18n_en_nav_overrides(db: Session) -> int:
    """Reset admin EN overrides for nav/page-title keys that drifted from nav labels."""
    n = 0
    for key, canonical in I18N_NAV_CANONICAL_EN.items():
        row = (
            db.query(models.UiI18nEnOverride)
            .filter(models.UiI18nEnOverride.key == key)
            .first()
        )
        if not row:
            continue
        cur = (row.en_text or "").strip()
        if cur and cur != canonical:
            row.en_text = canonical
            n += 1
    if n:
        db.commit()
    return n
