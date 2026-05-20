"""지식갤러리 한·영 공개 로케일."""

from __future__ import annotations

from . import models
from .kb_public_content import sanitize_meta_description, strip_leading_title_from_body_md
from .requirement_rich_text import is_html_format, sanitize_html


def kb_has_public_english(article: models.KnowledgeArticle) -> bool:
    title_en = (getattr(article, "title_en", None) or "").strip()
    body_en = (getattr(article, "body_md_en", None) or "").strip()
    return bool(title_en and body_en)


def kb_body_format_en(article: models.KnowledgeArticle) -> str:
    fmt = (getattr(article, "body_format_en", None) or "").strip().lower()
    if fmt in ("html", "markdown"):
        return fmt
    return (getattr(article, "body_format", None) or "markdown").strip().lower() or "markdown"


def kb_meta_title_for_locale(article: models.KnowledgeArticle, *, locale: str) -> str:
    from .routers.site_content_router import _meta_title_from_markdown

    if locale == "en":
        raw = (article.title_en or "").strip() or (article.title or "")
        return _meta_title_from_markdown(raw, "Knowledge Gallery")
    return _meta_title_from_markdown(article.title or "", "지식갤러리")


def kb_body_html_for_locale(article: models.KnowledgeArticle, *, locale: str, meta_title: str) -> str:
    from .routers.interview_router import _markdown_to_html

    if locale == "en":
        fmt = kb_body_format_en(article)
        raw = (article.body_md_en or "").strip()
        title_en = (article.title_en or "").strip() or meta_title
        if is_html_format(fmt):
            return sanitize_html(raw)
        md = strip_leading_title_from_body_md(raw, title_en)
        return _markdown_to_html(md)
    from .kb_body_rich import kb_body_html_fragment

    return kb_body_html_fragment(article, meta_title=meta_title)


def kb_excerpt_for_locale(article: models.KnowledgeArticle, *, locale: str) -> str:
    if locale == "en":
        return (article.excerpt_en or "").strip()
    return (article.excerpt or "").strip()


def kb_meta_description_for_locale(article: models.KnowledgeArticle, *, locale: str, meta_title: str) -> str:
    if locale == "en":
        raw = (article.meta_description_en or "").strip() or kb_excerpt_for_locale(article, locale="en")
        from .kb_body_rich import kb_body_plain_for_meta

        if not raw:
            raw = (article.body_md_en or "")[:500]
        return sanitize_meta_description(raw)
    raw = (article.meta_description or "").strip()
    if not raw:
        from .kb_body_rich import kb_body_plain_for_meta

        raw = kb_excerpt_for_locale(article, locale="ko") or kb_body_plain_for_meta(article)
    return sanitize_meta_description(raw)
