"""비로그인 홈 · 소셜 OAuth (/ia 는 / 로 리다이렉트)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import auth
from ..database import get_db
from ..guest_landing import IA_LANDING_DEPLOY_MARKER
from ..social_oauth import (
    complete_google_oauth,
    complete_kakao_oauth,
    google_authorize_url,
    google_oauth_configured,
    kakao_authorize_url,
    kakao_oauth_configured,
)

router = APIRouter(tags=["ia-landing"])


@router.get("/ia/_meta")
def ia_landing_meta():
    return {
        "ok": True,
        "ia_landing": True,
        "guest_home": True,
        "marker": IA_LANDING_DEPLOY_MARKER,
        "routes": ["/", "/ia", "/auth/oauth/google", "/auth/oauth/kakao"],
    }


@router.get("/ia", response_class=HTMLResponse)
def ia_landing_alias(request: Request, db: Session = Depends(get_db)):
    """레거시·북마크 URL → 정식 비로그인 홈."""
    user = auth.get_current_user(request, db)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url="/", status_code=301)


@router.get("/auth/oauth/google")
def oauth_google_start(request: Request, next: str = "/"):
    if not google_oauth_configured():
        return RedirectResponse(url="/?oauth_error=disabled", status_code=302)
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
def oauth_kakao_start(request: Request, next: str = "/"):
    if not kakao_oauth_configured():
        return RedirectResponse(url="/?oauth_error=disabled", status_code=302)
    return RedirectResponse(url=kakao_authorize_url(request, next), status_code=302)


@router.get("/auth/oauth/kakao/callback")
async def oauth_kakao_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    return await complete_kakao_oauth(request, db, code=code, state=state)
