"""요청당 User 1회 조회 — 미들웨어·라우트 공유."""

from __future__ import annotations

from starlette.requests import Request

from . import auth
from .database import SessionLocal


async def current_user_middleware(request: Request, call_next):
    request.state.current_user = None
    request.state.is_logged_in = False
    token = request.cookies.get("access_token")
    if token:
        db = SessionLocal()
        try:
            user = auth.get_user_from_token(token, db)
            if user:
                db.expunge(user)
                request.state.current_user = user
                request.state.is_logged_in = True
        finally:
            db.close()
    return await call_next(request)
