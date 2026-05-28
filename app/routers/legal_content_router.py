"""이용약관·개인정보처리방침 공개 조회."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import auth
from ..content_drafts import (
    DocKind,
    get_document_markdown,
    pdf_url_for,
    sync_content_drafts_from_files,
)
from ..database import get_db
from ..templates_config import templates
from .interview_router import _markdown_to_html
from sqlalchemy.orm import Session

router = APIRouter(tags=["legal_content"])


def _document_page(
    request: Request,
    db: Session,
    *,
    kind: DocKind,
    page_title_ko: str,
    page_title_en: str,
):
    sync_content_drafts_from_files(db, force=False)
    user = auth.get_current_user(request, db)
    md_ko = get_document_markdown(db, kind, lang="ko")  # type: ignore[arg-type]
    md_en = get_document_markdown(db, kind, lang="en")  # type: ignore[arg-type]
    if not md_ko.strip():
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": page_title_ko,
                "message": "문서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
                "message_en": "Could not load this document. Please try again later.",
            },
            status_code=503,
        )
    return templates.TemplateResponse(
        request,
        "site/content_document.html",
        {
            "request": request,
            "user": user,
            "page_title_ko": page_title_ko,
            "page_title_en": page_title_en,
            "body_html_ko": _markdown_to_html(md_ko),
            "body_html_en": _markdown_to_html(md_en),
            "pdf_url": pdf_url_for(kind),
        },
    )


@router.get("/terms", response_class=HTMLResponse)
def terms_public(request: Request, db: Session = Depends(get_db)):
    return _document_page(
        request,
        db,
        kind="terms",
        page_title_ko="이용약관",
        page_title_en="Terms of Service",
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy_public(request: Request, db: Session = Depends(get_db)):
    return _document_page(
        request,
        db,
        kind="privacy",
        page_title_ko="개인정보처리방침",
        page_title_en="Privacy Policy",
    )
