"""홈 연동 공지·FAQ 공개 상세 페이지."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..templates_config import templates
from .interview_router import _markdown_to_html

router = APIRouter(tags=["site_content"])


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
    body_html = _markdown_to_html(n.content or "")
    return templates.TemplateResponse(
        request,
        "site/notice_detail.html",
        {
            "request": request,
            "user": user,
            "notice": n,
            "body_html": body_html,
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
    answer_html = _markdown_to_html(f.answer or "")
    return templates.TemplateResponse(
        request,
        "site/faq_detail.html",
        {
            "request": request,
            "user": user,
            "faq": f,
            "answer_html": answer_html,
        },
    )
