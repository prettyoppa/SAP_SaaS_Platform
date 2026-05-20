"""홈 연동 공지·FAQ 공개 목록·상세 페이지."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..kb_body_rich import kb_body_plain_for_meta, kb_resolve_inline_entry
from ..kb_i18n import (
    kb_body_html_for_locale,
    kb_excerpt_for_locale,
    kb_has_public_english,
    kb_meta_description_for_locale,
    kb_meta_title_for_locale,
)
from ..kb_workflow import STATUS_PUBLISHED, is_publicly_visible
from ..offer_inquiry_service import public_request_url
from ..requirement_body import inline_image_response
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


@router.get("/kb-articles/{article_id}/body-inline")
def kb_article_body_inline(
    article_id: int,
    request: Request,
    iid: str = "",
    db: Session = Depends(get_db),
):
    """지식갤러리 본문 인라인 이미지 — 공개 글은 비로그인, 초안은 관리자만."""
    a = (
        db.query(models.KnowledgeArticle)
        .filter(models.KnowledgeArticle.id == article_id)
        .first()
    )
    if not a:
        return RedirectResponse(url="/", status_code=302)
    user = auth.get_current_user(request, db)
    if is_publicly_visible(a):
        pass
    elif user and user.is_admin:
        pass
    else:
        return RedirectResponse(url="/login", status_code=302)
    ent = kb_resolve_inline_entry(a, iid)
    redir = f"/kb/{a.slug}" if a.slug else "/"
    return inline_image_response(ent=ent, redirect_url=redir)


@router.get("/kb", response_class=HTMLResponse)
def kb_public_list(request: Request, db: Session = Depends(get_db)):
    """지식갤러리 전체 목록은 공개하지 않음(검색 유입용 개별 URL만)."""
    user = auth.get_current_user(request, db)
    return templates.TemplateResponse(
        request,
        "errors/simple_message.html",
        {
            "request": request,
            "user": user,
            "title": "지식갤러리",
            "message": "지식갤러리 목록은 제공하지 않습니다. 검색·공유 링크로 열 수 있는 글만 공개됩니다.",
            "message_en": "The knowledge gallery list is not available. Only individual articles opened via search or shared links are public.",
        },
        status_code=404,
    )


def _fetch_published_kb_article(slug: str, db: Session) -> models.KnowledgeArticle | None:
    now = _utc_now()
    return (
        db.query(models.KnowledgeArticle)
        .filter(
            models.KnowledgeArticle.slug == slug,
            models.KnowledgeArticle.is_published == True,
            models.KnowledgeArticle.workflow_status == STATUS_PUBLISHED,
            or_(
                models.KnowledgeArticle.published_at.is_(None),
                models.KnowledgeArticle.published_at <= now,
            ),
        )
        .first()
    )


def _kb_public_detail_response(
    request: Request,
    a: models.KnowledgeArticle,
    *,
    locale: str,
    user: models.User | None,
):
    loc = "en" if (locale or "").strip().lower() == "en" else "ko"
    if loc == "en" and not kb_has_public_english(a):
        return None
    meta_title = kb_meta_title_for_locale(a, locale=loc)
    title_html = _markdown_to_html(
        (a.title_en or a.title or "") if loc == "en" else (a.title or "")
    )
    body_html = kb_body_html_for_locale(a, locale=loc, meta_title=meta_title)
    meta_description = kb_meta_description_for_locale(a, locale=loc, meta_title=meta_title)
    excerpt = kb_excerpt_for_locale(a, locale=loc)
    show_excerpt = bool(excerpt) and not texts_overlap(
        excerpt, meta_title
    ) and not texts_overlap(excerpt, meta_description)
    canonical_path = f"/en/kb/{a.slug}" if loc == "en" else f"/kb/{a.slug}"
    canonical_url = public_request_url(request, canonical_path)
    alt_ko = public_request_url(request, f"/kb/{a.slug}")
    alt_en = (
        public_request_url(request, f"/en/kb/{a.slug}")
        if kb_has_public_english(a)
        else None
    )
    return templates.TemplateResponse(
        request,
        "site/kb_detail.html",
        {
            "request": request,
            "user": user,
            "article": a,
            "kb_categories": KB_CATEGORIES,
            "page_locale": loc,
            "title_html": title_html,
            "body_html": body_html,
            "meta_title": meta_title,
            "meta_description": meta_description,
            "canonical_url": canonical_url,
            "hreflang_ko": alt_ko,
            "hreflang_en": alt_en,
            "show_excerpt": show_excerpt,
            "excerpt_text": excerpt,
        },
    )


@router.get("/en/kb/{slug}", response_class=HTMLResponse)
def kb_public_detail_en(slug: str, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    a = _fetch_published_kb_article(slug, db)
    if not a:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "Knowledge Gallery",
                "message": "존재하지 않거나 비공개된 글입니다.",
                "message_en": "This article does not exist or is not published.",
            },
            status_code=404,
        )
    resp = _kb_public_detail_response(request, a, locale="en", user=user)
    if resp is None:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "Knowledge Gallery",
                "message": "영문 버전이 없습니다.",
                "message_en": "No English version is available for this article.",
            },
            status_code=404,
        )
    return resp


@router.get("/kb/{slug}", response_class=HTMLResponse)
def kb_public_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    a = _fetch_published_kb_article(slug, db)
    if not a:
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "지식갤러리",
                "message": "존재하지 않거나 비공개된 글입니다.",
                "message_en": "This article does not exist or is not published.",
            },
            status_code=404,
        )
    return _kb_public_detail_response(request, a, locale="ko", user=user)
