"""홈 히어로 제목·서브카피·부제(설명) — 기본값·정규화·안전 렌더."""

from __future__ import annotations

import re

from markupsafe import Markup, escape

DEFAULT_HOME_HERO_TITLE = "SAP 개발,<br>\nCatchy가 함께 하겠습니다."
DEFAULT_HOME_HERO_SUBCOPY = "with 8 Power Agents"
DEFAULT_HOME_HERO_DESC = "AI 에이전트가 요구사항을 분석하여 개발제안서를 생성합니다."

_BR_SPLIT_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
HERO_TITLE_MAX_LINES = 3


def normalize_hero_title_storage(raw: str) -> str:
    """저장용: 줄바꿈·<br> → 최대 3줄, <br>로 연결."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = _BR_SPLIT_RE.sub("\n", text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()][:HERO_TITLE_MAX_LINES]
    return "<br>".join(lines)


def hero_title_to_markup(raw: str) -> Markup:
    """표시용: 줄마다 block span (그라데이션 제목에서 <br> 줄바꿈 안정화)."""
    stored = normalize_hero_title_storage(raw)
    if not stored:
        return Markup("")
    parts = [escape(ln) for ln in _BR_SPLIT_RE.split(stored) if ln.strip()]
    parts = parts[:HERO_TITLE_MAX_LINES]
    if not parts:
        return Markup("")
    lines_html = "".join(f'<span class="hero-title-line">{p}</span>' for p in parts)
    return Markup(lines_html)


def resolve_home_hero_fields(settings: dict) -> dict[str, Markup | str]:
    """SiteSettings dict → 히어로 왼쪽 표시용 필드 (KO/EN). EN은 enrich_site_settings로 채워질 수 있음."""
    title_ko = (settings.get("home_hero_title") or "").strip() or DEFAULT_HOME_HERO_TITLE
    title_en = (settings.get("home_hero_title_en") or "").strip() or title_ko
    subcopy_ko = (settings.get("home_hero_subcopy") or "").strip() or DEFAULT_HOME_HERO_SUBCOPY
    subcopy_en = (settings.get("home_hero_subcopy_en") or "").strip() or subcopy_ko
    desc_ko = (settings.get("home_hero_desc") or "").strip() or DEFAULT_HOME_HERO_DESC
    desc_en = (settings.get("home_hero_desc_en") or "").strip() or desc_ko

    return {
        "title_markup_ko": hero_title_to_markup(title_ko),
        "title_markup_en": hero_title_to_markup(title_en),
        "subcopy_ko": escape(subcopy_ko),
        "subcopy_en": escape(subcopy_en),
        "desc_ko": escape(desc_ko),
        "desc_en": escape(desc_en),
    }
