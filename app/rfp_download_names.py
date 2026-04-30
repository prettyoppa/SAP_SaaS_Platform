"""RFC 5987 Content-Disposition 및 FS/납품 다운로드용 안전 파일명."""

from __future__ import annotations

import re
from urllib.parse import quote

# Windows·URL에서 문제 되는 문자 제거; 전체 basename 상한 (확장자 포함)
FILENAME_BASENAME_MAX_LEN = 120


def sanitize_path_component(raw: str, max_len: int) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # NTFS 금지 문자 및 제어문자
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", "_", s).strip("._")
    if len(s) > max_len:
        s = s[:max_len].rstrip("._")
    return s or "unnamed"


def fs_md_download_basename(program_id: str | None, title: str | None) -> str:
    """FS_{프로그램ID}_{요청제목}.md — 제목 길이는 상한까지 자름."""
    pid = sanitize_path_component(program_id or "NO_PID", 40)
    # "FS_", "_", ".md" 를 남긴 만큼 제목에 할당
    reserve = len("FS_") + len("_") + len(".md") + len(pid)
    tit_max = max(8, FILENAME_BASENAME_MAX_LEN - reserve)
    tit = sanitize_path_component(title or "untitled", tit_max)
    return f"FS_{pid}_{tit}.md"


def delivered_abap_download_basename(program_id: str | None, title: str | None) -> str:
    """DELIVERED_{프로그램ID}_{요청제목}.abap (basename 길이 상한 내)."""
    pid = sanitize_path_component(program_id or "NO_PID", 40)
    reserve = len("DELIVERED_") + len("_") + len(".abap") + len(pid)
    tit_max = max(8, FILENAME_BASENAME_MAX_LEN - reserve)
    tit = sanitize_path_component(title or "untitled", tit_max)
    return f"DELIVERED_{pid}_{tit}.abap"


def content_disposition_attachment(filename_utf8: str) -> str:
    """ASCII fallback filename + UTF-8 filename*."""
    fn = filename_utf8 or "download.md"
    ascii_fallback = re.sub(r"[^\x20-\x7E]", "_", fn)[:FILENAME_BASENAME_MAX_LEN] or "download.md"
    enc = quote(fn, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{enc}'
