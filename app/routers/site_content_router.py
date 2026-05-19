"""홈 연동 공지·FAQ 공개 목록·상세 페이지."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..kb_workflow import STATUS_PUBLISHED
from ..offer_inquiry_service import public_request_url
from ..templates_config import templates
from ..kb_public_content import (
    sanitize_meta_description,
    strip_leading_title_from_body_md,
    texts_overlap,
)
from .interview_router import _markdown_to_html

router = APIRouter(tags=["site_content"])

PER_PAGE = 10

KB_CATEGORIES = {
    "general": "일반",
    "abap": "신규 개발",
    "analysis": "분석·개선",
    "integration": "연동 개발",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _kb_published_filter(query):
    now = _utc_now()
    return query.filter(
        models.KnowledgeArticle.is_published == True,
        models.KnowledgeArticle.workflow_status == STATUS_PUBLISHED,
        or_(
            models.KnowledgeArticle.published_at.is_(None),
            models.KnowledgeArticle.published_at <= now,
        ),
    )


def _meta_title_from_markdown(md: str, fallback: str = "") -> str:
    """브라우저 탭용: 마크다운/태그 제거 후 짧은 순수 텍스트."""
    t = (md or "").strip()
    if not t:
        return fallback or "—"
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\s+", " ", t).strip()
    out = (t[:120] if t else "") or fallback or "—"
    return out


def _pagination_window(page: int, total_pages: int, span: int = 5) -> list[int]:
    if total_pages <= 0:
        return []
    half = span // 2
    start = max(1, page - half)
    end = min(total_pages, start + span - 1)
    start = max(1, end - span + 1)
    return list(range(start, end + 1))


@router.get("/notices", response_class=HTMLResponse)
def notice_public_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    page: int = 1,
):
    user = auth.get_current_user(request, db)
    page = max(1, page)
    term = (q or "").strip()

    base = db.query(models.Notice).filter(models.Notice.is_active == True)
    if term:
        like = f"%{term}%"
        base = base.filter(
            or_(models.Notice.title.ilike(like), models.Notice.title_en.ilike(like))
        )

    total = base.count()
    total_pages = max(1, math.ceil(total / PER_PAGE)) if total else 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PER_PAGE
    rows = (
        base.order_by(models.Notice.sort_order.asc(), models.Notice.created_at.asc())
        .offset(offset)
        .limit(PER_PAGE)
        .all()
    )

    list_rows: list[dict[str, Any]] = []
    for i, n in enumerate(rows):
        display_num = total - offset - i
        title_ko_html = _markdown_to_html(n.title or "")
        title_en_md = (getattr(n, "title_en", None) or "").strip() or (n.title or "")
        title_en_html = _markdown_to_html(title_en_md)
        list_rows.append(
            {
                "notice": n,
                "num": display_num,
                "title_html": title_ko_html,
                "title_en_html": title_en_html,
            }
        )

    return templates.TemplateResponse(
        request,
        "site/notice_list.html",
        {
            "request": request,
            "user": user,
            "q": term,
            "page": page,
            "per_page": PER_PAGE,
            "total": total,
            "total_pages": total_pages,
            "list_rows": list_rows,
            "page_nums": _pagination_window(page, total_pages),
        },
    )


@router.get("/faqs", response_class=HTMLResponse)
def faq_public_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    page: int = 1,
):
    user = auth.get_current_user(request, db)
    page = max(1, page)
    term = (q or "").strip()

    base = db.query(models.FAQ).filter(models.FAQ.is_active == True)
    if term:
        like = f"%{term}%"
        base = base.filter(
            or_(models.FAQ.question.ilike(like), models.FAQ.question_en.ilike(like))
        )

    total = base.count()
    total_pages = max(1, math.ceil(total / PER_PAGE)) if total else 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PER_PAGE
    rows = (
        base.order_by(models.FAQ.sort_order.asc(), models.FAQ.created_at.asc())
        .offset(offset)
        .limit(PER_PAGE)
        .all()
    )

    list_rows = []
    for i, f in enumerate(rows):
        display_num = total - offset - i
        q_ko_html = _markdown_to_html(f.question or "")
        q_en_md = (getattr(f, "question_en", None) or "").strip() or (f.question or "")
        q_en_html = _markdown_to_html(q_en_md)
        list_rows.append(
            {
                "faq": f,
                "num": display_num,
                "title_html": q_ko_html,
                "title_en_html": q_en_html,
            }
        )

    return templates.TemplateResponse(
        request,
        "site/faq_list.html",
        {
            "request": request,
            "user": user,
            "q": term,
            "page": page,
            "per_page": PER_PAGE,
            "total": total,
            "total_pages": total_pages,
            "list_rows": list_rows,
            "page_nums": _pagination_window(page, total_pages),
        },
    )


@router.get("/notices/{notice_id}", response_class=HTMLResponse)
def notice_public_detail(notice_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    n = (
        db.query(models.Notice)
        .filter(models.Notice.id == notice_id, models.Notice.is_active == True)
        .first()
    )
    if not n:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "공지사항",
                "message": "존재하지 않거나 비공개된 공지입니다.",
            },
            status_code=404,
        )
    title_html = _markdown_to_html(n.title or "")
    title_en_md = (getattr(n, "title_en", None) or "").strip() or (n.title or "")
    title_html_en = _markdown_to_html(title_en_md)
    body_html = _markdown_to_html(n.content or "")
    body_en_md = (getattr(n, "content_en", None) or "").strip() or (n.content or "")
    body_html_en = _markdown_to_html(body_en_md)
    meta_title = _meta_title_from_markdown(n.title, "공지")
    return templates.TemplateResponse(
        request,
        "site/notice_detail.html",
        {
            "request": request,
            "user": user,
            "notice": n,
            "title_html": title_html,
            "title_html_en": title_html_en,
            "body_html": body_html,
            "body_html_en": body_html_en,
            "meta_title": meta_title,
        },
    )


@router.get("/faqs/{faq_id}", response_class=HTMLResponse)
def faq_public_detail(faq_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    f = db.query(models.FAQ).filter(models.FAQ.id == faq_id, models.FAQ.is_active == True).first()
    if not f:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {"request": request, "user": user, "title": "FAQ", "message": "존재하지 않거나 비공개된 항목입니다."},
            status_code=404,
        )
    question_html = _markdown_to_html(f.question or "")
    q_en_md = (getattr(f, "question_en", None) or "").strip() or (f.question or "")
    question_html_en = _markdown_to_html(q_en_md)
    answer_html = _markdown_to_html(f.answer or "")
    a_en_md = (getattr(f, "answer_en", None) or "").strip() or (f.answer or "")
    answer_html_en = _markdown_to_html(a_en_md)
    meta_title = _meta_title_from_markdown(f.question, "FAQ")
    return templates.TemplateResponse(
        request,
        "site/faq_detail.html",
        {
            "request": request,
            "user": user,
            "faq": f,
            "question_html": question_html,
            "question_html_en": question_html_en,
            "answer_html": answer_html,
            "answer_html_en": answer_html_en,
            "meta_title": meta_title,
        },
    )


@router.get("/kb", response_class=HTMLResponse)
def kb_public_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    category: str = "",
    page: int = 1,
):
    user = auth.get_current_user(request, db)
    page = max(1, page)
    term = (q or "").strip()
    cat = (category or "").strip().lower()
    if cat and cat not in KB_CATEGORIES:
        cat = ""

    base = _kb_published_filter(db.query(models.KnowledgeArticle))
    if cat:
        base = base.filter(models.KnowledgeArticle.category == cat)
    if term:
        like = f"%{term}%"
        base = base.filter(
            or_(
                models.KnowledgeArticle.title.ilike(like),
                models.KnowledgeArticle.excerpt.ilike(like),
                models.KnowledgeArticle.tags.ilike(like),
            )
        )

    total = base.count()
    total_pages = max(1, math.ceil(total / PER_PAGE)) if total else 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PER_PAGE
    rows = (
        base.order_by(
            models.KnowledgeArticle.sort_order.asc(),
            models.KnowledgeArticle.published_at.desc(),
            models.KnowledgeArticle.id.desc(),
        )
        .offset(offset)
        .limit(PER_PAGE)
        .all()
    )

    list_rows: list[dict[str, Any]] = []
    for a in rows:
        list_rows.append(
            {
                "article": a,
                "title_html": _markdown_to_html(a.title or ""),
                "excerpt_html": _markdown_to_html(a.excerpt or ""),
            }
        )

    canonical_url = public_request_url(request, "/kb")
    meta_description = (
        "SAP 지식갤러리 — 신규 개발, 분석·개선, 연동 개발 실무 가이드와 체크리스트."
    )
    return templates.TemplateResponse(
        request,
        "site/kb_list.html",
        {
            "request": request,
            "user": user,
            "q": term,
            "category": cat,
            "kb_categories": KB_CATEGORIES,
            "page": page,
            "per_page": PER_PAGE,
            "total": total,
            "total_pages": total_pages,
            "list_rows": list_rows,
            "page_nums": _pagination_window(page, total_pages),
            "canonical_url": canonical_url,
            "meta_description": meta_description,
        },
    )


@router.get("/kb/{slug}", response_class=HTMLResponse)
def kb_public_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    now = _utc_now()
    a = (
        db.query(models.KnowledgeArticle)
        .filter(
            models.KnowledgeArticle.slug == slug,
            models.KnowledgeArticle.is_published == True,
            or_(
                models.KnowledgeArticle.published_at.is_(None),
                models.KnowledgeArticle.published_at <= now,
            ),
        )
        .first()
    )
    if not a:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "SAP 지식갤러리",
                "message": "존재하지 않거나 비공개된 글입니다.",
                "message_en": "This article does not exist or is not published.",
            },
            status_code=404,
        )
    meta_title = _meta_title_from_markdown(a.title, "SAP 지식갤러리")
    body_md = strip_leading_title_from_body_md(a.body_md or "", meta_title)
    body_en_md_raw = (a.body_md_en or "").strip() or (a.body_md or "")
    body_en_md = strip_leading_title_from_body_md(body_en_md_raw, meta_title)
    title_html = _markdown_to_html(a.title or "")
    title_en_md = (a.title_en or "").strip() or (a.title or "")
    title_html_en = _markdown_to_html(title_en_md)
    body_html = _markdown_to_html(body_md)
    body_html_en = _markdown_to_html(body_en_md)
    raw_meta = (a.meta_description or "").strip() or _meta_title_from_markdown(
        a.excerpt or body_md, meta_title
    )
    meta_description = sanitize_meta_description(raw_meta)
    show_excerpt = bool((a.excerpt or "").strip()) and not texts_overlap(
        a.excerpt, meta_title
    ) and not texts_overlap(a.excerpt, meta_description)
    canonical_url = public_request_url(request, f"/kb/{a.slug}")
    return templates.TemplateResponse(
        request,
        "site/kb_detail.html",
        {
            "request": request,
            "user": user,
            "article": a,
            "kb_categories": KB_CATEGORIES,
            "title_html": title_html,
            "title_html_en": title_html_en,
            "body_html": body_html,
            "body_html_en": body_html_en,
            "meta_title": meta_title,
            "meta_description": meta_description,
            "canonical_url": canonical_url,
            "show_excerpt": show_excerpt,
        },
    )
