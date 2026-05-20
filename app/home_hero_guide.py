"""홈 히어로 «사용 안내» — Markdown 타이핑 데모용."""

from __future__ import annotations

import re


def markdown_typing_lines(md: str) -> list[str]:
    """Markdown을 줄 단위 평문으로 (타이핑 애니메이션용)."""
    out: list[str] = []
    for raw in (md or "").splitlines():
        s = raw.strip()
        if not s:
            out.append("")
            continue
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"__(.+?)__", r"\1", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = re.sub(r"^[-*+]\s+", "• ", s)
        s = re.sub(r"^\d+\.\s+", "", s)
        out.append(s.strip())
    while out and not out[-1]:
        out.pop()
    return out if out else [""]


def home_guide_has_text(md: str) -> bool:
    return any((ln or "").strip() for ln in markdown_typing_lines(md))


def home_guide_text_bundle(settings: dict) -> dict:
    """히어로 타이핑 데모 JS용 { ko: {lines, html}, en: … }."""
    from .routers.interview_router import _markdown_to_html

    def _pack(md: str) -> dict:
        raw = (md or "").strip()
        return {
            "lines": markdown_typing_lines(raw),
            "html": _markdown_to_html(raw) if raw else "",
        }

    return {
        "ko": _pack(str(settings.get("home_guide_text_md") or "")),
        "en": _pack(str(settings.get("home_guide_text_md_en") or "")),
    }
