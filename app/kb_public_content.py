"""지식갤러리 공개 페이지용 본문·메타 정리."""

from __future__ import annotations

import re


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _heading_plain(line: str) -> str:
    return _collapse_ws(re.sub(r"^#{1,6}\s*", "", (line or "").strip()))


def texts_overlap(a: str, b: str, *, min_len: int = 36) -> bool:
    """제목·요약·메타가 사실상 같은 문장인지."""
    aa = _collapse_ws(a).lower()
    bb = _collapse_ws(b).lower()
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    shorter, longer = (aa, bb) if len(aa) <= len(bb) else (bb, aa)
    if len(shorter) < min_len:
        return False
    return shorter in longer


def sanitize_meta_description(raw: str, *, max_len: int = 160) -> str:
    """검색 스니펫용 — URL·공백 정리 (본문에 노출하지 않음)."""
    t = (raw or "").strip()
    t = re.sub(r"https?://\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" .,;")
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"
    return t


def strip_leading_title_from_body_md(body_md: str, title: str) -> str:
    """본문 맨 앞 # 제목이 article.title 과 같으면 제거."""
    body = (body_md or "").lstrip()
    title_plain = _heading_plain(title)
    if not body or not title_plain:
        return body_md or ""

    m = re.match(r"^#\s+(.+?)\s*(?:\r?\n|$)", body)
    if m and _heading_plain(m.group(1)) == title_plain:
        body = body[m.end() :].lstrip()

    # AI가 제목을 일반 문단으로 한 번 더 넣은 경우
    lines = body.splitlines()
    if lines and _heading_plain(lines[0]) == title_plain:
        body = "\n".join(lines[1:]).lstrip()

    return body
