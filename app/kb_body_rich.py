"""지식갤러리 본문 — HTML(서식·이미지) / Markdown 저장·인라인 이미지."""

from __future__ import annotations

from typing import Any, Optional

from . import models
from .requirement_rich_text import html_to_plain_text, is_html_format, process_submitted_html, sanitize_html
from .requirement_screenshots import entries_from_json, entries_to_json, remove_stored_entries


def kb_screenshot_entries(article: models.KnowledgeArticle) -> list[dict[str, Any]]:
    return entries_from_json(getattr(article, "body_screenshots_json", None))


def kb_resolve_inline_entry(article: models.KnowledgeArticle, iid: str) -> Optional[dict[str, Any]]:
    key = (iid or "").strip()
    if not key:
        return None
    return next(
        (e for e in kb_screenshot_entries(article) if str(e.get("inline_id") or "") == key),
        None,
    )


def apply_kb_body(
    article: models.KnowledgeArticle,
    user: models.User,
    raw: str,
    fmt: str,
) -> Optional[str]:
    """
    본문·body_format·인라인 이미지 JSON 반영.
    오류 시 에러 키 문자열 반환, 성공 시 None.
    """
    existing = kb_screenshot_entries(article)
    fmt_norm = (fmt or "markdown").strip().lower()
    if fmt_norm == "html":
        html, entries, err = process_submitted_html(
            user_id=int(user.id),
            raw_html=raw,
            req_id=int(article.id),
            existing_entries=existing,
            kind="kb",
        )
        if err:
            return err
        article.body_md = html or ""
        article.body_format = "html"
        article.body_screenshots_json = entries_to_json(entries) if entries else None
        return None
    if fmt_norm != "markdown":
        fmt_norm = "markdown"
    plain = (raw or "").strip()
    if existing:
        remove_stored_entries(existing)
    article.body_md = plain
    article.body_format = fmt_norm
    article.body_screenshots_json = None
    return None


def kb_body_plain_for_meta(article: models.KnowledgeArticle) -> str:
    """메타·중복 검사용 평문."""
    fmt = (getattr(article, "body_format", None) or "markdown").strip().lower()
    raw = article.body_md or ""
    if is_html_format(fmt):
        return html_to_plain_text(raw)
    return raw.strip()


def kb_body_html_fragment(article: models.KnowledgeArticle, *, meta_title: str) -> str:
    """공개·미리보기용 본문 HTML."""
    from .kb_public_content import strip_leading_title_from_body_md
    from .routers.interview_router import _markdown_to_html

    fmt = (getattr(article, "body_format", None) or "markdown").strip().lower()
    if is_html_format(fmt):
        return sanitize_html(article.body_md or "")
    md = strip_leading_title_from_body_md(article.body_md or "", meta_title)
    return _markdown_to_html(md)
