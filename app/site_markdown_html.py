"""공지·FAQ·홈 팝업 등 회원용 사이트 마크다운 → HTML."""

from __future__ import annotations

import markdown

_SITE_MD_EXTENSIONS = ["fenced_code", "tables", "nl2br"]


def site_markdown_to_html(md: str | None) -> str:
    """Python-Markdown(GFM 확장)으로 제목·본문 렌더."""
    raw = (md or "").strip()
    if not raw:
        return ""
    return markdown.markdown(raw, extensions=_SITE_MD_EXTENSIONS)
