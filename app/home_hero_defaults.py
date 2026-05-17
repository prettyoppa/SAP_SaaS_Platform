"""홈 히어로 기본 HTML (관리자 미설정 시)."""

from __future__ import annotations

import re

_STYLE_ATTR_RE = re.compile(r'\sstyle=(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
_BG_DECL_RE = re.compile(
    r"background(?:-color|-image|-size|-position|-repeat|-attachment)?\s*:[^;\"']+;?\s*",
    re.IGNORECASE,
)


def sanitize_home_hero_html(raw: str) -> str:
    """히어로 HTML에서 배경 관련 inline style 제거(점 그리드 배경 유지)."""
    text = (raw or "").strip()
    if not text:
        return ""

    def _clean_style(match: re.Match[str]) -> str:
        quote, body = match.group(1), match.group(2)
        cleaned = _BG_DECL_RE.sub("", body).strip().strip(";")
        if not cleaned:
            return ""
        return f' style={quote}{cleaned}{quote}'

    return _STYLE_ATTR_RE.sub(_clean_style, text)


DEFAULT_HOME_HERO_HTML = """<h1 class="hero-title">
  SAP 개발, Catchy가<br>함께 하겠습니다.<br>
  <span class="hero-power-agents text-gradient" data-i18n="hero.powerAgents">with 8 Power Agents</span>
</h1>
<p class="hero-sub">AI 에이전트가 요구사항을 분석하여 개발제안서를 생성합니다.</p>"""
