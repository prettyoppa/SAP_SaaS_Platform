"""홈 히어로 제목·서브카피·부제(설명) — 기본값·정규화·안전 렌더."""

from __future__ import annotations

import re

from markupsafe import Markup, escape

DEFAULT_HOME_HERO_TITLE = "SAP 개발,<br>\nCatchy가 함께 하겠습니다."
DEFAULT_HOME_HERO_SUBCOPY = "with 8 Power Agents"
DEFAULT_HOME_HERO_DESC = "AI 에이전트가 요구사항을 분석하여 개발제안서를 생성합니다."

_BR_SPLIT_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def normalize_hero_title_storage(raw: str) -> str:
    """저장용: 줄바꿈·<br> → 최대 2줄, <br>로 연결."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = _BR_SPLIT_RE.sub("\n", text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()][:2]
    return "<br>".join(lines)


def hero_title_to_markup(raw: str) -> Markup:
    """표시용: 줄 단위 이스케이프 후 <br> (최대 2줄)."""
    stored = normalize_hero_title_storage(raw)
    if not stored:
        return Markup("")
    parts = [escape(ln) for ln in _BR_SPLIT_RE.split(stored) if ln.strip()]
    return Markup("<br>".join(parts[:2]))


def resolve_home_hero_fields(settings: dict) -> dict[str, Markup | str]:
    """SiteSettings dict → 히어로 왼쪽 표시용 필드."""
    title_raw = (settings.get("home_hero_title") or "").strip() or DEFAULT_HOME_HERO_TITLE
    subcopy_raw = (settings.get("home_hero_subcopy") or "").strip() or DEFAULT_HOME_HERO_SUBCOPY
    desc_raw = (settings.get("home_hero_desc") or "").strip() or DEFAULT_HOME_HERO_DESC

    return {
        "title_markup": hero_title_to_markup(title_raw),
        "subcopy": escape(subcopy_raw),
        "desc": escape(desc_raw),
    }
