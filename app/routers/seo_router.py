"""robots.txt · sitemap.xml · llms.txt — 공개 URL만 색인 대상으로 노출."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..llms_txt import llms_txt_for_request
from ..offer_inquiry_service import site_public_origin
from ..seo_indexing import (
    faq_has_indexable_answer,
    kb_has_indexable_body_en,
    kb_has_indexable_body_ko,
    notice_has_indexable_body,
)

router = APIRouter(tags=["seo"])
_log = logging.getLogger("uvicorn.error")

# 로그인·민감 경로 — prefix 일치 시 차단 (아래 Allow 규칙이 우선인 경로 제외)
_DISALLOW_PREFIXES = (
    "/admin",
    "/api",
    "/account",
    "/rfp/",
    "/abap-analysis",
    "/integration",
    "/request-console",
    "/login",
    "/register",
    "/logout",
    "/payments",
    "/billing",
    "/codelib",
    "/reviews",
    "/dev/",
    "/preview/",
    "/ia",
    "/auth/oauth/",
)

# 공개 SEO 랜딩 (회원 전용 메뉴 허브 /abap-analysis · /integration 은 제외)
_PUBLIC_LANDING_PATHS = (
    "/",
    "/about",
    "/services/abap",
    "/notices",
    "/faqs",
    "/kb",
    "/terms",
    "/privacy",
    "/llms.txt",
)


def _lastmod_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _sitemap_url_block(loc: str, lastmod: str | None, changefreq: str, priority: str) -> str:
    lines = ["  <url>", f"    <loc>{escape(loc)}</loc>"]
    if lastmod:
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
    lines.append(f"    <changefreq>{changefreq}</changefreq>")
    lines.append(f"    <priority>{priority}</priority>")
    lines.append("  </url>")
    return "\n".join(lines)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt(request: Request) -> PlainTextResponse:
    origin = site_public_origin(request)
    allow_lines = [f"Allow: {p}" for p in _PUBLIC_LANDING_PATHS]
    allow_lines.extend(
        [
            "Allow: /kb/",
            "Allow: /en/kb/",
            "Allow: /notices/",
            "Allow: /faqs/",
        ]
    )
    disallow = "\n".join(f"Disallow: {p}" for p in _DISALLOW_PREFIXES)
    body = "\n".join(
        [
            "User-agent: *",
            *allow_lines,
            disallow,
            "",
            "User-agent: GPTBot",
            "Allow: /",
            "Allow: /llms.txt",
            "Allow: /about",
            "Allow: /kb/",
            "",
            "User-agent: ChatGPT-User",
            "Allow: /",
            "Allow: /llms.txt",
            "Allow: /about",
            "Allow: /kb/",
            "",
            "User-agent: ClaudeBot",
            "Allow: /",
            "Allow: /llms.txt",
            "Allow: /about",
            "Allow: /kb/",
            "",
            f"Sitemap: {origin}/sitemap.xml",
            "",
        ]
    )
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8")


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(llms_txt_for_request(request), media_type="text/plain; charset=utf-8")


def _build_sitemap_entries(origin: str, db: Session) -> list[str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries: list[str] = []

    static_pages = [
        (f"{origin}/", today, "weekly", "1.0"),
        (f"{origin}/about", today, "monthly", "0.9"),
        (f"{origin}/services/abap", today, "weekly", "0.85"),
        (f"{origin}/kb", today, "daily", "0.85"),
        (f"{origin}/terms", today, "yearly", "0.4"),
        (f"{origin}/privacy", today, "yearly", "0.4"),
    ]
    for loc, lastmod, changefreq, priority in static_pages:
        entries.append(_sitemap_url_block(loc, lastmod, changefreq, priority))

    notices = (
        db.query(models.Notice)
        .filter(models.Notice.is_active == True)
        .order_by(models.Notice.created_at.desc(), models.Notice.id.desc())
        .all()
    )
    indexable_notices = [n for n in notices if notice_has_indexable_body(n)]
    if indexable_notices:
        entries.append(_sitemap_url_block(f"{origin}/notices", today, "weekly", "0.7"))
    for n in indexable_notices:
        lm = _lastmod_iso(getattr(n, "updated_at", None) or n.created_at) or today
        entries.append(
            _sitemap_url_block(
                f"{origin}/notices/{n.id}",
                lm,
                "monthly",
                "0.6",
            )
        )

    faqs = (
        db.query(models.FAQ)
        .filter(models.FAQ.is_active == True)
        .order_by(models.FAQ.created_at.desc(), models.FAQ.id.desc())
        .all()
    )
    indexable_faqs = [f for f in faqs if faq_has_indexable_answer(f)]
    if indexable_faqs:
        entries.append(_sitemap_url_block(f"{origin}/faqs", today, "weekly", "0.7"))
    for f in indexable_faqs:
        lm = _lastmod_iso(getattr(f, "updated_at", None) or f.created_at) or today
        entries.append(
            _sitemap_url_block(
                f"{origin}/faqs/{f.id}",
                lm,
                "monthly",
                "0.6",
            )
        )

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    from ..kb_workflow import STATUS_PUBLISHED

    articles = (
        db.query(models.KnowledgeArticle)
        .filter(
            models.KnowledgeArticle.is_published == True,
            models.KnowledgeArticle.workflow_status == STATUS_PUBLISHED,
            or_(
                models.KnowledgeArticle.published_at.is_(None),
                models.KnowledgeArticle.published_at <= now_naive,
            ),
        )
        .order_by(models.KnowledgeArticle.updated_at.desc(), models.KnowledgeArticle.id.desc())
        .all()
    )
    for a in articles:
        lm = _lastmod_iso(getattr(a, "updated_at", None) or a.published_at or a.created_at) or today
        if kb_has_indexable_body_ko(a):
            entries.append(
                _sitemap_url_block(
                    f"{origin}/kb/{a.slug}",
                    lm,
                    "monthly",
                    "0.8",
                )
            )
        if kb_has_indexable_body_en(a):
            entries.append(
                _sitemap_url_block(
                    f"{origin}/en/kb/{a.slug}",
                    lm,
                    "monthly",
                    "0.7",
                )
            )
    return entries


def _sitemap_xml_response(entries: list[str]) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml; charset=utf-8")


@router.get("/sitemap.xml")
def sitemap_xml(request: Request, db: Session = Depends(get_db)) -> Response:
    origin = site_public_origin(request)
    try:
        return _sitemap_xml_response(_build_sitemap_entries(origin, db))
    except Exception:
        _log.exception("sitemap_xml failed; returning static URLs only")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fallback = [
            _sitemap_url_block(f"{origin}/", today, "weekly", "1.0"),
            _sitemap_url_block(f"{origin}/about", today, "monthly", "0.9"),
            _sitemap_url_block(f"{origin}/services/abap", today, "weekly", "0.85"),
            _sitemap_url_block(f"{origin}/kb", today, "daily", "0.85"),
        ]
        return _sitemap_xml_response(fallback)
