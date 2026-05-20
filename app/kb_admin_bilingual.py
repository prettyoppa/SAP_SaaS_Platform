"""지식갤러리 관리자 — 한·영 필드 저장."""

from __future__ import annotations

from . import models


def apply_kb_bilingual_from_form(
    article: models.KnowledgeArticle,
    *,
    also_english: bool,
    title_en: str = "",
    excerpt_en: str = "",
    meta_description_en: str = "",
    body_md_en: str = "",
) -> None:
    if also_english:
        article.title_en = (title_en or "").strip() or None
        article.excerpt_en = (excerpt_en or "").strip() or None
        article.meta_description_en = (meta_description_en or "").strip()[:320] or None
        article.body_md_en = (body_md_en or "").strip() or None
        fmt = (getattr(article, "body_format", None) or "markdown").strip().lower()
        article.body_format_en = fmt if fmt in ("html", "markdown") else "markdown"
    else:
        article.title_en = None
        article.excerpt_en = None
        article.meta_description_en = None
        article.body_md_en = None
        article.body_format_en = None
