"""홈 히어로 «사용 안내» — 평문 타이핑 데모용."""

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


def markdown_to_plain_text(md: str, *, single_line: bool = False) -> str:
    """목록·타일용 — 마크다운 기호 제거 평문(풀 HTML 렌더 생략)."""
    lines_out: list[str] = []
    for raw in (md or "").splitlines():
        s = raw.strip()
        if not s:
            if not single_line:
                lines_out.append("")
            continue
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*+]\s+(?:\[[ xX]\]\s*)?", "", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"__(.+?)__", r"\1", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = re.sub(r"^\d+\.\s+", "", s)
        lines_out.append(s.strip())
    while lines_out and not lines_out[-1]:
        lines_out.pop()
    if single_line:
        return " ".join(ln for ln in lines_out if ln).strip()
    return "\n".join(lines_out).strip()


def home_guide_has_text(md: str) -> bool:
    return any((ln or "").strip() for ln in markdown_typing_lines(md))


def locale_text_bundle(ko: str, en: str) -> dict:
    """타이핑 데모 JS용 { ko: { lines }, en: … } (평문 줄)."""

    def _pack(text: str) -> dict:
        raw = (text or "").strip()
        return {"lines": markdown_typing_lines(raw)}

    return {
        "ko": _pack(str(ko or "")),
        "en": _pack(str(en or "")),
    }


def home_guide_text_bundle(settings: dict) -> dict:
    """히어로 «사용 안내» 타이핑 데모."""
    return locale_text_bundle(
        str(settings.get("home_guide_text_md") or ""),
        str(settings.get("home_guide_text_md_en") or ""),
    )


def home_tile_desc_bundle(ko: str, en: str) -> dict:
    """홈 서비스 타일 설명 타이핑 데모."""
    bundle = locale_text_bundle(str(ko or ""), str(en or ""))
    for loc in ("ko", "en"):
        block = bundle.get(loc) or {}
        lines = block.get("lines") or []
        block["lines"] = [ln for ln in lines if str(ln or "").strip()]
        bundle[loc] = block
    return bundle
