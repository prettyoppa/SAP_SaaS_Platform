"""Google / Kakao OAuth — 간편 로그인·경량 회원 가입."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import auth, models

logger = logging.getLogger("uvicorn.error")

_OAUTH_STATE_SALT = "oauth-state-v1"
_OAUTH_STATE_MAX_AGE = 900  # 15분


def _oauth_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(auth.SECRET_KEY, salt=_OAUTH_STATE_SALT)


def _normalize_email(raw: str | None) -> str | None:
    try:
        validated = validate_email((raw or "").strip(), check_deliverability=False)
        return validated.normalized
    except EmailNotValidError:
        return None


def _public_base_url(request: Request) -> str:
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    return str(request.base_url).rstrip("/")


def _safe_next_path(raw: str | None) -> str:
    p = (raw or "").strip()
    if not p.startswith("/") or p.startswith("//"):
        return "/ia"
    if "://" in p:
        return "/ia"
    return p or "/ia"


def google_oauth_configured() -> bool:
    return bool(
        (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
        and (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    )


def kakao_oauth_configured() -> bool:
    return bool((os.environ.get("KAKAO_OAUTH_CLIENT_ID") or "").strip())


def create_oauth_state(provider: str, next_path: str) -> str:
    return _oauth_serializer().dumps(
        {"p": provider, "n": _safe_next_path(next_path), "r": secrets.token_urlsafe(8)}
    )


def parse_oauth_state(state: str) -> tuple[str, str] | None:
    try:
        data = _oauth_serializer().loads(state, max_age=_OAUTH_STATE_MAX_AGE)
        provider = data.get("p")
        nxt = data.get("n")
        if provider not in ("google", "kakao"):
            return None
        return provider, _safe_next_path(nxt if isinstance(nxt, str) else None)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def google_authorize_url(request: Request, next_path: str) -> str:
    base = _public_base_url(request)
    redirect_uri = f"{base}/auth/oauth/google/callback"
    params = {
        "client_id": (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "state": create_oauth_state("google", next_path),
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def kakao_authorize_url(request: Request, next_path: str) -> str:
    base = _public_base_url(request)
    redirect_uri = f"{base}/auth/oauth/kakao/callback"
    params = {
        "client_id": (os.environ.get("KAKAO_OAUTH_CLIENT_ID") or "").strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": create_oauth_state("kakao", next_path),
        "scope": "account_email",
    }
    return "https://kauth.kakao.com/oauth/authorize?" + urlencode(params)


async def _exchange_google_code(request: Request, code: str) -> dict[str, Any] | None:
    base = _public_base_url(request)
    redirect_uri = f"{base}/auth/oauth/google/callback"
    data = {
        "code": code,
        "client_id": (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip(),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post("https://oauth2.googleapis.com/token", data=data)
        if token_res.status_code != 200:
            logger.warning("Google token exchange failed: %s", token_res.text[:200])
            return None
        token_json = token_res.json()
        access_token = token_json.get("access_token")
        if not access_token:
            return None
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            return None
        return user_res.json()


async def _exchange_kakao_code(request: Request, code: str) -> dict[str, Any] | None:
    base = _public_base_url(request)
    redirect_uri = f"{base}/auth/oauth/kakao/callback"
    client_id = (os.environ.get("KAKAO_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("KAKAO_OAUTH_CLIENT_SECRET") or "").strip()
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            "https://kauth.kakao.com/oauth/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code != 200:
            logger.warning("Kakao token exchange failed: %s", token_res.text[:200])
            return None
        token_json = token_res.json()
        access_token = token_json.get("access_token")
        if not access_token:
            return None
        user_res = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"property_keys": '["kakao_account.email", "kakao_account.profile"]'},
        )
        if user_res.status_code != 200:
            return None
        return user_res.json()


def _profile_from_google(payload: dict[str, Any]) -> tuple[str | None, str]:
    email = _normalize_email(payload.get("email"))
    name = (payload.get("name") or payload.get("given_name") or "").strip()
    if not name and email:
        name = email.split("@", 1)[0]
    if not name:
        name = "회원"
    return email, name[:120]


def _profile_from_kakao(payload: dict[str, Any]) -> tuple[str | None, str]:
    account = payload.get("kakao_account") or {}
    email = _normalize_email(account.get("email"))
    profile = account.get("profile") or {}
    name = (profile.get("nickname") or "").strip()
    if not name and email:
        name = email.split("@", 1)[0]
    if not name:
        name = "회원"
    return email, name[:120]


def _issue_login_response(
    request: Request,
    user: models.User,
    redirect_url: str,
) -> RedirectResponse:
    token = auth.create_access_token({"sub": user.email})
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    lang = getattr(user, "preferred_lang", None) or "ko"
    if lang not in ("ko", "en"):
        lang = "ko"
    response.set_cookie(
        key="ui_lang",
        value=lang,
        httponly=False,
        max_age=86400 * 400,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    tz = (getattr(user, "timezone", None) or "").strip()
    if tz:
        response.set_cookie(
            key="viewer_tz",
            value=tz[:64],
            httponly=True,
            max_age=86400 * 400,
            path="/",
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def _oauth_error_redirect(next_path: str, code: str) -> RedirectResponse:
    sep = "&" if "?" in next_path else "?"
    return RedirectResponse(url=f"{next_path}{sep}oauth_error={code}", status_code=302)


def find_or_create_oauth_member(
    db: Session,
    *,
    email: str,
    full_name: str,
    request: Request,
) -> models.User | None:
    email_norm = _normalize_email(email)
    if not email_norm:
        return None

    existing = db.query(models.User).filter(models.User.email == email_norm).first()
    if existing:
        if not existing.is_active:
            return None
        from .trial_service import maybe_grant_experience_trial

        maybe_grant_experience_trial(db, existing)
        db.commit()
        db.refresh(existing)
        return existing

    consent_at = datetime.utcnow()
    new_user = models.User(
        email=email_norm,
        full_name=(full_name or "회원")[:120],
        company=None,
        phone_number=None,
        phone_verified=False,
        hashed_password=auth.hash_password(secrets.token_urlsafe(32)),
        email_verified=True,
        is_consultant=False,
        consultant_application_pending=False,
        preferred_lang="ko",
        billing_currency="KRW",
        ops_email_opt_in=True,
        ops_sms_opt_in=False,
        marketing_email_opt_in=False,
        marketing_sms_opt_in=False,
        consent_updated_at=consent_at,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    from .trial_service import maybe_grant_experience_trial

    maybe_grant_experience_trial(db, new_user)
    db.commit()
    db.refresh(new_user)

    from .wallet_topup_notifications import job_notify_admins_new_registration, schedule_wallet_notification

    schedule_wallet_notification(job_notify_admins_new_registration, int(new_user.id))

    from .platform_audit import EVENT_MEMBER_REGISTERED, record_event

    record_event(db, new_user, EVENT_MEMBER_REGISTERED)
    return new_user


async def complete_google_oauth(
    request: Request,
    db: Session,
    *,
    code: str | None,
    state: str | None,
) -> RedirectResponse:
    parsed = parse_oauth_state(state or "")
    if not parsed or parsed[0] != "google":
        return _oauth_error_redirect("/ia", "state")
    _, next_path = parsed
    if not code:
        return _oauth_error_redirect(next_path, "cancelled")
    if not google_oauth_configured():
        return _oauth_error_redirect(next_path, "disabled")

    payload = await _exchange_google_code(request, code)
    if not payload:
        return _oauth_error_redirect(next_path, "token")
    email, full_name = _profile_from_google(payload)
    if not email:
        return _oauth_error_redirect(next_path, "email")

    user = find_or_create_oauth_member(db, email=email, full_name=full_name, request=request)
    if not user:
        return _oauth_error_redirect(next_path, "account")

    return _issue_login_response(request, user, next_path)


async def complete_kakao_oauth(
    request: Request,
    db: Session,
    *,
    code: str | None,
    state: str | None,
) -> RedirectResponse:
    parsed = parse_oauth_state(state or "")
    if not parsed or parsed[0] != "kakao":
        return _oauth_error_redirect("/ia", "state")
    _, next_path = parsed
    if not code:
        return _oauth_error_redirect(next_path, "cancelled")
    if not kakao_oauth_configured():
        return _oauth_error_redirect(next_path, "disabled")

    payload = await _exchange_kakao_code(request, code)
    if not payload:
        return _oauth_error_redirect(next_path, "token")
    email, full_name = _profile_from_kakao(payload)
    if not email:
        return _oauth_error_redirect(next_path, "email")

    user = find_or_create_oauth_member(db, email=email, full_name=full_name, request=request)
    if not user:
        return _oauth_error_redirect(next_path, "account")

    return _issue_login_response(request, user, next_path)
