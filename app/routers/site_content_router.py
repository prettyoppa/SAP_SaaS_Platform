"""홈 연동 공지·FAQ 공개 목록·상세 페이지."""

from __future__ import annotations

import math
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..templates_config import templates
from .interview_router import _markdown_to_html

router = APIRouter(tags=["site_content"])

PER_PAGE = 10


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
