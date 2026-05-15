"""요구사항 리치 텍스트(HTML) — 삽입·정화·인라인 이미지 저장."""

from __future__ import annotations

import html
import re
import uuid
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .requirement_screenshots import (
    MAX_SCREENSHOT_BYTES,
    MAX_SCREENSHOT_COUNT,
    MAX_SCREENSHOT_TOTAL_BYTES,
    _decode_data_url,
    _store_bytes,
    entries_from_json,
    remove_stored_entries,
)

ALLOWED_TAGS = frozenset(
    {"p", "br", "div", "span", "strong", "b", "em", "i", "u", "ul", "ol", "li", "img"}
)
VOID_TAGS = frozenset({"br", "img"})
_IMG_SRC_DATA = re.compile(r"^data:image/", re.I)
_INLINE_URL_RE = re.compile(
    r"/abap-analysis/(\d+)/requirement-inline\?([^\"'\s>]+)",
    re.I,
)


def is_html_format(fmt: Optional[str]) -> bool:
    return (fmt or "").strip().lower() == "html"


def html_to_plain_text(raw: str) -> str:
    """LLM·글자 수 검증용 평문."""
    if not raw or not str(raw).strip():
        return ""
    s = str(raw)
    if "<" not in s:
        return s.strip()
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def plain_text_length(raw: str, *, fmt: Optional[str] = None) -> int:
    if is_html_format(fmt) or ("<" in (raw or "") and ">" in (raw or "")):
        return len(html_to_plain_text(raw))
    return len((raw or "").strip())


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t not in ALLOWED_TAGS:
            return
        safe_attrs: list[tuple[str, str]] = []
        if t == "img":
            allow = {"src", "alt", "data-inline-id", "class"}
            for k, v in attrs:
                lk = (k or "").lower()
                if lk not in allow or v is None:
                    continue
                if lk == "src" and not (
                    _IMG_SRC_DATA.match(v)
                    or _INLINE_URL_RE.search(v)
                    or v.startswith("/abap-analysis/")
                ):
                    continue
                safe_attrs.append((lk, html.escape(v, quote=True)))
        elif t in ("p", "div", "span", "strong", "b", "em", "i", "u", "li"):
            for k, v in attrs:
                if (k or "").lower() == "class" and v:
                    safe_attrs.append(("class", html.escape(v, quote=True)))
        parts = " ".join(f'{k}="{v}"' for k, v in safe_attrs)
        if t in VOID_TAGS:
            self._out.append(f"<{t}{(' ' + parts) if parts else ''}>")
        else:
            self._out.append(f"<{t}{(' ' + parts) if parts else ''}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ALLOWED_TAGS and t not in VOID_TAGS:
            self._out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        self._out.append(html.escape(data))

    def get_html(self) -> str:
        return "".join(self._out).strip()


def sanitize_html(raw: str) -> str:
    if not raw or not str(raw).strip():
        return ""
    p = _Sanitizer()
    try:
        p.feed(str(raw))
        p.close()
    except Exception:
        return html.escape(html_to_plain_text(raw))
    out = p.get_html()
    return out or ""


def _inline_url(req_id: int, inline_id: str) -> str:
    return f"/abap-analysis/{int(req_id)}/requirement-inline?iid={inline_id}"


def _parse_inline_id_from_src(src: str) -> Optional[str]:
    if not src:
        return None
    try:
        u = urlparse(src)
        qs = parse_qs(u.query)
        iid = (qs.get("iid") or [None])[0]
        return str(iid).strip() if iid else None
    except Exception:
        return None


def _count_imgs(html_str: str) -> int:
    return len(re.findall(r"<img\b", html_str or "", flags=re.I))


def process_submitted_html(
    *,
    user_id: int,
    raw_html: str,
    req_id: int,
    existing_entries: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], Optional[str]]:
    """
    data: URL·기존 inline URL을 정리해 저장용 HTML·screenshots JSON 엔트리 반환.
    """
    cleaned = sanitize_html(raw_html)
    if not cleaned:
        remove_stored_entries(existing_entries)
        return "", [], None

    if _count_imgs(cleaned) > MAX_SCREENSHOT_COUNT:
        return cleaned, existing_entries, "screenshot_too_many"

    by_id: dict[str, dict[str, Any]] = {
        str(e.get("inline_id")): e
        for e in existing_entries
        if e.get("inline_id")
    }
    used_ids: set[str] = set()
    new_entries: list[dict[str, Any]] = []
    total_bytes = 0
    err_key: list[Optional[str]] = [None]

    img_pattern = re.compile(r"<img\b([^>]*)>", re.I)

    def _repl(match: re.Match[str]) -> str:
        nonlocal total_bytes
        if err_key[0]:
            return ""
        attr_blob = match.group(1) or ""
        src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', attr_blob, re.I)
        iid_m = re.search(r'\bdata-inline-id=["\']([^"\']+)["\']', attr_blob, re.I)
        src = src_m.group(1) if src_m else ""
        inline_id = (iid_m.group(1) if iid_m else None) or _parse_inline_id_from_src(src)
        alt_m = re.search(r'\balt=["\']([^"\']*)["\']', attr_blob, re.I)
        alt = html.escape((alt_m.group(1) if alt_m else "") or "캡처", quote=True)

        if _IMG_SRC_DATA.match(src):
            try:
                raw, mime = _decode_data_url(src)
            except ValueError as e:
                return ""
            if len(raw) > MAX_SCREENSHOT_BYTES:
                err_key[0] = "screenshot_too_large"
                return ""
            total_bytes += len(raw)
            if total_bytes > MAX_SCREENSHOT_TOTAL_BYTES:
                err_key[0] = "screenshot_total_too_large"
                return ""
            inline_id = inline_id or uuid.uuid4().hex
            fname = f"inline-{inline_id[:8]}.jpg"
            stored = _store_bytes(user_id, raw, mime, fname)
            if not stored:
                return ""
            stored["inline_id"] = inline_id
            new_entries.append(stored)
            used_ids.add(inline_id)
            url = _inline_url(req_id, inline_id)
            return (
                f'<img src="{html.escape(url, quote=True)}" '
                f'data-inline-id="{html.escape(inline_id, quote=True)}" '
                f'alt="{alt}" class="req-inline-img"/>'
            )

        if inline_id and inline_id in by_id:
            ent = by_id[inline_id]
            used_ids.add(inline_id)
            new_entries.append(ent)
            url = _inline_url(req_id, inline_id)
            return (
                f'<img src="{html.escape(url, quote=True)}" '
                f'data-inline-id="{html.escape(inline_id, quote=True)}" '
                f'alt="{alt}" class="req-inline-img"/>'
            )

        if src and _INLINE_URL_RE.search(src):
            iid2 = _parse_inline_id_from_src(src)
            if iid2 and iid2 in by_id:
                used_ids.add(iid2)
                new_entries.append(by_id[iid2])
                return (
                    f'<img src="{html.escape(_inline_url(req_id, iid2), quote=True)}" '
                    f'data-inline-id="{html.escape(iid2, quote=True)}" '
                    f'alt="{alt}" class="req-inline-img"/>'
                )
        return ""

    out_html = img_pattern.sub(_repl, cleaned)
    if err_key[0]:
        remove_stored_entries(new_entries)
        return cleaned, existing_entries, err_key[0]

    out_html = sanitize_html(out_html)

    for eid, ent in by_id.items():
        if eid not in used_ids:
            remove_stored_entries([ent])

    if len(new_entries) > MAX_SCREENSHOT_COUNT:
        remove_stored_entries(new_entries)
        return cleaned, existing_entries, "screenshot_too_many"

    return out_html, new_entries, None


def legacy_gallery_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """inline_id 없는 예전 하단 갤러리용."""
    return [e for e in entries if not e.get("inline_id")]