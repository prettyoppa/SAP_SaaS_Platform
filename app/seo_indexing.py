"""Search indexing helpers — sitemap inclusion and page-level noindex rules."""

from __future__ import annotations

from . import models
from .kb_i18n import kb_has_public_english

# 본문이 이보다 짧으면 sitemap·색인 대상에서 제외 (Soft 404 방지)
_MIN_KB_BODY_CHARS = 200
_MIN_NOTICE_BODY_CHARS = 80
_MIN_FAQ_ANSWER_CHARS = 40


def _text_len(*parts: str | None) -> int:
    return len("".join((p or "").strip() for p in parts))


def notice_has_indexable_body(notice: models.Notice) -> bool:
    return _text_len(notice.content, getattr(notice, "content_en", None)) >= _MIN_NOTICE_BODY_CHARS


def faq_has_indexable_answer(faq: models.FAQ) -> bool:
    return _text_len(faq.answer, getattr(faq, "answer_en", None)) >= _MIN_FAQ_ANSWER_CHARS


def kb_has_indexable_body_ko(article: models.KnowledgeArticle) -> bool:
    if not (article.slug or "").strip():
        return False
    return _text_len(article.body_md) >= _MIN_KB_BODY_CHARS


def kb_has_indexable_body_en(article: models.KnowledgeArticle) -> bool:
    if not kb_has_public_english(article):
        return False
    if not (article.slug or "").strip():
        return False
    return _text_len(article.body_md_en) >= _MIN_KB_BODY_CHARS
