import logging
import os
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..email_smtp import email_verification_enabled, send_registration_otp_email, send_verification_email
from ..templates_config import templates

router = APIRouter()
logger = logging.getLogger(__name__)


def _send_verification_email_bg(to_addr: str, verify_url: str) -> None:
    """HTTP 응답을 막지 않기 위해 별도 스레드에서 발송. 실패 시 로그만 남김(재발송으로 복구)."""
    try:
        send_verification_email(to_addr, verify_url)
        logger.info("Verification email sent to %s", to_addr)
    except Exception:
        logger.exception("Verification email failed for %s", to_addr)


def _schedule_verification_email(to_addr: str, verify_url: str) -> None:
    threading.Thread(
        target=_send_verification_email_bg, args=(to_addr, verify_url), daemon=True
    ).start()


def _normalize_email_strict(raw: str) -> str | None:
    """RFC 기반 구문 검증(가장 흔한 방식). DNS MX 조회는 배포 환경에 따라 생략."""
    try:
        validated = validate_email(raw.strip(), check_deliverability=False)
        return validated.normalized
    except EmailNotValidError:
        return None


def _public_base_url(request: Request) -> str:
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    return str(request.base_url).rstrip("/")


def _access_token_cookie_args(request: Request, token: str) -> dict:
    """브라우저별 세션 쿠키. path/samesite/secure 명시로 예측 가능하게 둠."""
    return {
        "key": "access_token",
        "value": token,
        "httponly": True,
        "max_age": 86400,
        "path": "/",
        "samesite": "lax",
        "secure": request.url.scheme == "https",
    }


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    verified: str | None = None,
    verify: str | None = None,
    registered: str | None = None,
):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    ctx = {}
    if verified == "1":
        ctx["verified_ok"] = True
    if verify == "invalid":
        ctx["verify_invalid"] = True
    if registered == "1":
        ctx["registered_ok"] = True
    return templates.TemplateResponse(request, "login.html", ctx)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": True},
            status_code=400,
        )
    user = db.query(models.User).filter(models.User.email == email_norm).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": True},
            status_code=400,
        )
    if email_verification_enabled() and not user.email_verified:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "email_not_verified", "email": email_norm},
            status_code=400,
        )
    token = auth.create_access_token({"sub": user.email})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(**_access_token_cookie_args(request, token))
    return response


@router.get("/api/companies")
def get_companies(q: str = "", db: Session = Depends(get_db)):
    """회사명 자동완성 API – 기존 회원의 회사명 목록 반환"""
    query = db.query(models.User.company).filter(models.User.company != None)
    if q:
        query = query.filter(models.User.company.ilike(f"%{q}%"))
    companies = sorted({row[0] for row in query.all() if row[0]})
    return JSONResponse(companies[:20])


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    return templates.TemplateResponse(
        request,
        "register.html",
        {"settings": settings, "email_verification": email_verification_enabled()},
    )


@router.get("/register/check-email", response_class=HTMLResponse)
def register_check_email_page(request: Request, resent: str | None = None):
    return templates.TemplateResponse(
        request,
        "register_check_email.html",
        {"resent_ok": resent == "1"},
    )


@router.post("/register/send-verification-code")
def register_send_verification_code(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    """회원가입용 6자리 인증 코드 메일 발송 (같은 탭에서 코드 입력)."""
    if not email_verification_enabled():
        return JSONResponse({"ok": False, "error": "disabled"}, status_code=400)
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        return JSONResponse({"ok": False, "error": "invalid_email"}, status_code=400)
    if db.query(models.User).filter(models.User.email == email_norm).first():
        return JSONResponse({"ok": False, "error": "duplicate"}, status_code=400)
    now = datetime.utcnow()
    row = db.query(models.EmailRegistrationCode).filter(
        models.EmailRegistrationCode.email == email_norm
    ).first()
    if row and row.last_sent_at and (now - row.last_sent_at).total_seconds() < 60:
        return JSONResponse({"ok": False, "error": "cooldown"}, status_code=429)
    code = auth.generate_registration_otp()
    code_hash = auth.registration_code_hash(email_norm, code)
    expires = now + timedelta(minutes=auth.registration_otp_ttl_minutes())
    try:
        send_registration_otp_email(email_norm, code)
    except Exception as e:
        logger.exception("send_registration_otp_email: %s", e)
        return JSONResponse({"ok": False, "error": "send_failed"}, status_code=500)
    if row:
        row.code_hash = code_hash
        row.expires_at = expires
        row.last_sent_at = now
    else:
        db.add(
            models.EmailRegistrationCode(
                email=email_norm,
                code_hash=code_hash,
                expires_at=expires,
                last_sent_at=now,
            )
        )
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    company: str = Form(""),
    password: str = Form(...),
    verification_code: str = Form(""),
    db: Session = Depends(get_db),
):
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "invalid_email",
                "settings": settings,
                "email_verification": email_verification_enabled(),
            },
            status_code=400,
        )

    existing = db.query(models.User).filter(models.User.email == email_norm).first()
    if existing:
        settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "duplicate",
                "settings": settings,
                "email_verification": email_verification_enabled(),
            },
            status_code=400,
        )
    want_verify = email_verification_enabled()
    settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    ev = email_verification_enabled()

    if want_verify:
        code_in = "".join(c for c in (verification_code or "") if c.isdigit())
        if len(code_in) != 6:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "no_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        row = db.query(models.EmailRegistrationCode).filter(
            models.EmailRegistrationCode.email == email_norm
        ).first()
        if not row:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "no_code_sent",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        if datetime.utcnow() > row.expires_at:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "expired_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        if not auth.registration_codes_equal(email_norm, code_in, row.code_hash):
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "bad_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        db.delete(row)

    new_user = models.User(
        email=email_norm,
        full_name=full_name,
        company=company or None,
        hashed_password=auth.hash_password(password),
        email_verified=True,
    )
    db.add(new_user)
    db.commit()

    if want_verify:
        return RedirectResponse(url="/login?registered=1", status_code=302)

    token = auth.create_access_token({"sub": new_user.email})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(**_access_token_cookie_args(request, token))
    return response


@router.get("/verify-email")
def verify_email(token: str = "", db: Session = Depends(get_db)):
    email = auth.parse_email_verification_token(token)
    if not email:
        return RedirectResponse(url="/login?verify=invalid", status_code=302)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return RedirectResponse(url="/login?verify=invalid", status_code=302)
    if user.email_verified:
        return RedirectResponse(url="/login", status_code=302)
    user.email_verified = True
    db.commit()
    return RedirectResponse(url="/login?verified=1", status_code=302)


@router.post("/resend-verification")
def resend_verification(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    """미인증 계정에 한해 인증 메일 재발송. 존재 여부는 응답에 노출하지 않음."""
    if not email_verification_enabled():
        return RedirectResponse(url="/login", status_code=302)
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        return RedirectResponse(url="/register/check-email?resent=1", status_code=302)
    user = db.query(models.User).filter(models.User.email == email_norm).first()
    if not user:
        logger.info(
            "resend-verification: no user for %s — not sending (must match signup email)",
            email_norm,
        )
    elif user.email_verified:
        logger.info("resend-verification: %s already verified — not sending", email_norm)
    else:
        vtoken = auth.create_email_verification_token(email_norm)
        base = _public_base_url(request)
        link = f"{base}/verify-email?token={quote(vtoken, safe='')}"
        logger.info("resend-verification: queueing verification email for %s", email_norm)
        _schedule_verification_email(email_norm, link)
    return RedirectResponse(url="/register/check-email?resent=1", status_code=302)


@router.get("/logout")
def logout(request: Request):
    try:
        request.session.clear()
    except Exception:
        pass
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(
        "access_token",
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response
