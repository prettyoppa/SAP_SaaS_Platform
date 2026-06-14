"""IA/레이아웃 시안 — /preview/ia (기존 사이트와 분리된 테스트용)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..home_counts import home_tile_counts
from ..menu_landing import home_tile_stage_links
from ..request_hub_access import consultant_menu_matched_scope
from ..templates_config import templates

router = APIRouter(tags=["preview-ia"])

_PREVIEW_ROOT = "/preview/ia"


def _mock_client_requests():
    return [
        {
            "id": "demo-1",
            "title_ko": "월말 마감 리포트 자동화",
            "title_en": "Month-end closing report automation",
            "type_ko": "새 프로그램",
            "type_en": "New development",
            "status_ko": "제안서 검토",
            "status_en": "Review proposal",
            "updated_ko": "2일 전",
            "updated_en": "2 days ago",
            "href": "/services/abap",
            "demo": True,
        },
        {
            "id": "demo-2",
            "title_ko": "ZFI 전표 인터페이스 성능",
            "title_en": "ZFI posting interface performance",
            "type_ko": "분석·개선",
            "type_en": "Analysis & improve",
            "status_ko": "AI 인터뷰 중",
            "status_en": "AI interview",
            "updated_ko": "오늘",
            "updated_en": "Today",
            "href": "/abap-analysis",
            "demo": True,
        },
    ]


def _mock_consultant_inbox():
    return [
        {
            "id": "demo-c1",
            "title_ko": "SD 출하 프로세스 오류 수정",
            "title_en": "SD shipping process fix",
            "menu_ko": "신규 개발",
            "menu_en": "New dev",
            "budget_ko": "예산 협의",
            "budget_en": "Budget TBD",
            "demo": True,
        },
        {
            "id": "demo-c2",
            "title_ko": "외부 WMS ↔ SAP 연동",
            "title_en": "External WMS ↔ SAP integration",
            "menu_ko": "연동",
            "menu_en": "Integration",
            "budget_ko": "₩12,000,000",
            "budget_en": "₩12M",
            "demo": True,
        },
    ]


def _client_summary_from_counts(home_counts) -> dict | None:
    if not home_counts:
        return None
    rfp = home_counts.get("rfp") or {}
    ana = home_counts.get("abap_analysis") or {}
    intg = home_counts.get("integration") or {}

    def _sum(bucket: dict) -> int:
        return int(sum(int(bucket.get(k, 0) or 0) for k in ("draft", "in_progress", "analysis", "proposal", "delivery")))

    return {
        "total": _sum(rfp) + _sum(ana) + _sum(intg),
        "active": int(rfp.get("in_progress", 0) or 0)
        + int(rfp.get("proposal", 0) or 0)
        + int(ana.get("in_progress", 0) or 0)
        + int(ana.get("proposal", 0) or 0)
        + int(intg.get("in_progress", 0) or 0)
        + int(intg.get("proposal", 0) or 0),
        "draft": int(rfp.get("draft", 0) or 0) + int(ana.get("draft", 0) or 0) + int(intg.get("draft", 0) or 0),
    }


@router.get("/preview/ia", response_class=HTMLResponse)
def preview_ia_landing(request: Request):
    user = getattr(request.state, "current_user", None)
    return templates.TemplateResponse(
        request,
        "preview/ia/landing.html",
        {
            "user": user,
            "preview_root": _PREVIEW_ROOT,
        },
    )


@router.get("/preview/ia/client", response_class=HTMLResponse)
def preview_ia_client_home(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    summary = None
    stage_links = None
    if user:
        try:
            counts = home_tile_counts(
                db,
                user.id,
                is_admin=bool(user.is_admin),
                consultant_matched=consultant_menu_matched_scope(user),
            )
            summary = _client_summary_from_counts(counts)
            stage_links = {
                "all_draft": "/services/abap",
                "rfp": home_tile_stage_links("rfp"),
                "analysis": home_tile_stage_links("analysis"),
                "integration": home_tile_stage_links("integration"),
            }
        except Exception:
            summary = None
    return templates.TemplateResponse(
        request,
        "preview/ia/client_home.html",
        {
            "user": user,
            "preview_root": _PREVIEW_ROOT,
            "preview_role": "client",
            "requests": _mock_client_requests(),
            "summary": summary,
            "stage_links": stage_links,
            "using_demo_data": True,
        },
    )


@router.get("/preview/ia/client/new", response_class=HTMLResponse)
def preview_ia_client_new(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    return templates.TemplateResponse(
        request,
        "preview/ia/client_new.html",
        {
            "user": user,
            "preview_root": _PREVIEW_ROOT,
            "preview_role": "client",
        },
    )


@router.get("/preview/ia/consultant", response_class=HTMLResponse)
def preview_ia_consultant_home(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    is_consultant = bool(user and (user.is_consultant or user.is_admin))
    return templates.TemplateResponse(
        request,
        "preview/ia/consultant_home.html",
        {
            "user": user,
            "preview_root": _PREVIEW_ROOT,
            "preview_role": "consultant",
            "inbox": _mock_consultant_inbox(),
            "is_consultant": is_consultant,
            "console_url": "/request-console",
        },
    )


@router.get("/preview/ia/switch/{role}")
def preview_ia_switch_role(role: str):
    role = (role or "").strip().lower()
    if role == "consultant":
        return RedirectResponse(url=f"{_PREVIEW_ROOT}/consultant", status_code=302)
    return RedirectResponse(url=f"{_PREVIEW_ROOT}/client", status_code=302)
