"""요구사항 본문(평문/HTML·인라인 이미지) — ABAP·RFP·연동 공통."""

from __future__ import annotations

import os
from typing import Any, Literal, Optional

from fastapi import Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from . import models, r2_storage
from .requirement_rich_text import (
    html_to_plain_text,
    is_html_format,
    legacy_gallery_entries,
    process_submitted_html,
    sanitize_html,
)
from .requirement_screenshots import (
    duplicate_entries,
    entries_from_json,
    entries_to_json,
    remove_stored_entries,
)

RequirementKind = Literal["abap", "rfp", "integration"]

_PATH_BASE: dict[RequirementKind, str] = {
    "abap": "/abap-analysis",
    "rfp": "/rfp",
    "integration": "/integration",
}

_FIELDS: dict[RequirementKind, tuple[str, str]] = {
    "abap": ("requirement_text", "requirement_text_format"),
    "rfp": ("description", "description_format"),
    "integration": ("description", "description_format"),
}


def path_base(kind: RequirementKind) -> str:
    return _PATH_BASE[kind]


def text_field(kind: RequirementKind) -> str:
    return _FIELDS[kind][0]


def format_field(kind: RequirementKind) -> str:
    return _FIELDS[kind][1]


def screenshot_entries(row: Any) -> list[dict[str, Any]]:
    return entries_from_json(getattr(row, "requirement_screenshots_json", None))


def set_screenshot_entries(row: Any, entries: list[dict[str, Any]]) -> None:
    row.requirement_screenshots_json = entries_to_json(entries)


def body_plain(row: Any, kind: RequirementKind) -> str:
    text_f, fmt_f = _FIELDS[kind]
    fmt = (getattr(row, fmt_f, None) or "plain").strip().lower()
    raw = getattr(row, text_f, None) or ""
    if is_html_format(fmt):
        return html_to_plain_text(raw)
    return str(raw).strip()


def has_body_context(row: Any, kind: RequirementKind) -> bool:
    if body_plain(row, kind).strip():
        return True
    return any(e.get("inline_id") for e in screenshot_entries(row))


def apply_body(
    row: Any,
    user: models.User,
    raw: str,
    fmt: str,
    kind: RequirementKind,
) -> Optional[str]:
    """본문·포맷·인라인 이미지 저장. 오류 키 또는 None."""
    text_f, fmt_f = _FIELDS[kind]
    existing = screenshot_entries(row)
    fmt_norm = (fmt or "plain").strip().lower()
    if is_html_format(fmt_norm):
        html, entries, err = process_submitted_html(
            user_id=user.id,
            raw_html=raw,
            req_id=int(row.id),
            existing_entries=existing,
            kind=kind,
        )
        if err:
            return err
        setattr(row, text_f, html)
        setattr(row, fmt_f, "html")
        set_screenshot_entries(row, entries)
        return None
    plain = (raw or "").strip()
    if existing:
        remove_stored_entries(existing)
    setattr(row, text_f, plain)
    setattr(row, fmt_f, "plain")
    set_screenshot_entries(row, [])
    return None


def display_ctx(row: Any, kind: RequirementKind, req_id: int) -> dict[str, Any]:
    text_f, fmt_f = _FIELDS[kind]
    fmt = (getattr(row, fmt_f, None) or "plain").strip().lower()
    raw = getattr(row, text_f, None) or ""
    all_shots = screenshot_entries(row)
    legacy = legacy_gallery_entries(all_shots)
    base = path_base(kind)
    return {
        "requirement_text_format": fmt,
        "requirement_html_safe": sanitize_html(raw) if is_html_format(fmt) else "",
        "requirement_plain_text": raw if not is_html_format(fmt) else "",
        "requirement_screenshot_entries": legacy or ([] if is_html_format(fmt) else all_shots),
        "screenshot_url_base": f"{base}/{req_id}/requirement-screenshot",
    }


def duplicate_screenshots(
    entries: list[dict[str, Any]], *, user_id: int
) -> list[dict[str, Any]]:
    return duplicate_entries(entries, user_id=user_id)


def inline_image_response(
    *,
    ent: Optional[dict[str, Any]],
    redirect_url: str,
) -> RedirectResponse | FileResponse:
    if not ent:
        return RedirectResponse(url=redirect_url, status_code=302)
    path = ent.get("path")
    fname = ent.get("filename") or "screenshot.png"
    if not path:
        return RedirectResponse(url=redirect_url, status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=redirect_url, status_code=302)
        return RedirectResponse(
            url=r2_storage.presigned_get_url(ref, fname, inline=True),
            status_code=302,
        )
    if not os.path.isfile(ref):
        return RedirectResponse(url=redirect_url, status_code=302)
    media = "image/png"
    low = fname.lower()
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        media = "image/jpeg"
    elif low.endswith(".webp"):
        media = "image/webp"
    return FileResponse(ref, media_type=media, filename=fname, content_disposition_type="inline")


def resolve_inline_entry(
    row: Any, iid: str
) -> Optional[dict[str, Any]]:
    key = (iid or "").strip()
    if not key:
        return None
    return next(
        (e for e in screenshot_entries(row) if str(e.get("inline_id") or "") == key),
        None,
    )
