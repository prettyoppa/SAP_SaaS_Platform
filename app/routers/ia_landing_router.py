"""신규 홈 시안 /ia · 소셜 OAuth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth
from ..database import get_db
from ..social_oauth import (
    complete_google_oauth,
    complete_kakao_oauth,
    google_authorize_url,
    google_oauth_configured,
    kakao_authorize_url,
    kakao_oauth_configured,
)
from ..templates_config import templates

router = APIRouter(tags=["ia-landing"])

IA_LANDING_DEPLOY_MARKER = "20260616-ia-r1"


@router.get("/ia/_meta")
def ia_landing_meta():
    return {
        "ok": True,
        "ia_landing": True,
        "marker": IA_LANDING_DEPLOY_MARKER,
        "routes": ["/ia", "/auth/oauth/google", "/auth/oauth/kakao"],
    }


@router.get("/ia", response_class=HTMLResponse)
def ia_landing(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if user:
        return RedirectResponse(url="/", status_code=302)

    oauth_error = (request.query_params.get("oauth_error") or "").strip()
    return templates.TemplateResponse(
        request,
        "ia/landing.html",
        {
            "request": request,
            "user": None,
            "seo_noindex": True,
            "google_oauth_enabled": google_oauth_configured(),
            "kakao_oauth_enabled": kakao_oauth_configured(),
            "oauth_next": "/",
            "oauth_error": oauth_error,
        },
    )


@router.get("/auth/oauth/google")
def oauth_google_start(request: Request, next: str = "/ia"):
    if not google_oauth_configured():
        return RedirectResponse(url="/ia?oauth_error=disabled", status_code=302)
    return RedirectResponse(url=google_authorize_url(request, next), status_code=302)


@router.get("/auth/oauth/google/callback")
async def oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    return await complete_google_oauth(request, db, code=code, state=state)


@router.get("/auth/oauth/kakao")
def oauth_kakao_start(request: Request, next: str = "/ia"):
    if not kakao_oauth_configured():
        return RedirectResponse(url="/ia?oauth_error=disabled", status_code=302)
    return RedirectResponse(url=kakao_authorize_url(request, next), status_code=302)


@router.get("/auth/oauth/kakao/callback")
async def oauth_kakao_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    return await complete_kakao_oauth(request, db, code=code, state=state)
