import logging
import os
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import available_timezones

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..account_lifecycle import deletion_grace_days, refresh_admin_flag_for_user
from ..database import get_db
from ..email_smtp import (
    email_verification_enabled,
    send_account_deletion_started_email,
    send_email_change_confirm_email,
    send_email_change_notice_previous,
    send_email_changed_completed_notice,
    send_registration_otp_email,
    send_verification_email,
)
from ..templates_config import templates
from ..sms_sender import send_registration_otp_sms

router = APIRouter()
logger = logging.getLogger(__name__)


def _delete_auth_cookie(response: RedirectResponse, request: Request) -> None:
    response.delete_cookie(
        "access_token",
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _schedule_bg(fn, *args, **kwargs):
    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("Background task failed (%s)", getattr(fn, "__name__", repr(fn)))

    threading.Thread(target=_run, daemon=True).start()


def _safe_login_redirect_next(raw: str | None) -> str | None:
    """로그인 후 이동: 같은 사이트 내 상대 경로만 허용."""
    if raw is None:
        return None
    p = (raw or "").strip()
    if not p.startswith("/") or p.startswith("//"):
        return None
    return p

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


def _normalize_phone_e164(raw: str) -> str | None:
    """국제번호(E.164): +[국가번호][가입자번호], 총 8~15자리."""
    s = (raw or "").strip()
    if not s:
        return None
    s = re.sub(r"[\s\-\(\)]", "", s)
    if not s.startswith("+"):
        return None
    digits = s[1:]
    if not digits.isdigit():
        return None
    if len(digits) < 8 or len(digits) > 15:
        return None
    return f"+{digits}"


def _form_bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "on", "yes", "y")


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


_VIEWER_TZ_COOKIE = "viewer_tz"
_MAX_VIEWER_TZ_LEN = 64


def _viewer_tz_cookie_args(request: Request, tz: str | None) -> dict:
    v = (tz or "").strip()
    if len(v) > _MAX_VIEWER_TZ_LEN:
        v = v[:_MAX_VIEWER_TZ_LEN]
    return {
        "key": _VIEWER_TZ_COOKIE,
        "value": v,
        "httponly": True,
        "max_age": 86400 * 400,
        "path": "/",
        "samesite": "lax",
        "secure": request.url.scheme == "https",
    }


def _delete_viewer_tz_cookie(response: RedirectResponse, request: Request) -> None:
    response.delete_cookie(
        _VIEWER_TZ_COOKIE,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _sync_viewer_tz_cookie(response: RedirectResponse, request: Request, user: models.User | None) -> None:
    if user is None:
        return
    tz = (getattr(user, "timezone", None) or "").strip()
    response.set_cookie(**_viewer_tz_cookie_args(request, tz))


_MAX_PROFILE_FULL_NAME = 120
_MAX_PROFILE_COMPANY = 255
_MIN_PASSWORD_LEN = 8


def _parse_profile_full_name(raw: str) -> tuple[str | None, str | None]:
    """반환: (값, 오류코드). 값은 비어 있으면 None."""
    s = (raw or "").strip()
    if not s:
        return None, "full_name_required"
    if len(s) > _MAX_PROFILE_FULL_NAME:
        return None, "full_name_too_long"
    return s, None


def _parse_profile_company(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    return s[:_MAX_PROFILE_COMPANY]


def _parse_profile_timezone(raw: str | None) -> tuple[str | None, str | None]:
    """반환: (저장값 None=비움, 오류코드)."""
    s = (raw or "").strip()
    if not s:
        return None, None
    if len(s) > _MAX_VIEWER_TZ_LEN or s not in available_timezones():
        return None, "timezone_invalid"
    return s, None


def _parse_new_password(raw: str | None) -> tuple[str | None, str | None]:
    s = (raw or "").strip()
    if len(s) < _MIN_PASSWORD_LEN:
        return None, "password_short"
    if len(s) > 256:
        return None, "password_long"
    return s, None


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    verified: str | None = None,
    verify: str | None = None,
    registered: str | None = None,
    deletion_started: str | None = None,
    delete_cancelled: str | None = None,
    delete_cancel_invalid: str | None = None,
    email_change_invalid: str | None = None,
):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    ctx = {}
    nxt = _safe_login_redirect_next(request.query_params.get("next"))
    if nxt:
        ctx["login_next"] = nxt
    if verified == "1":
        ctx["verified_ok"] = True
    if verify == "invalid":
        ctx["verify_invalid"] = True
    if registered == "1":
        ctx["registered_ok"] = True
    if deletion_started == "1":
        ctx["deletion_started_notice"] = True
    if delete_cancelled == "1":
        ctx["delete_cancelled_notice"] = True
    if email_change_invalid == "1":
        ctx["email_change_invalid"] = True
    if delete_cancel_invalid == "1":
        ctx["delete_cancel_invalid"] = True
    return templates.TemplateResponse(request, "login.html", ctx)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_path: str = Form(""),
    db: Session = Depends(get_db),
):
    def _ctx(**kw):
        nx = _safe_login_redirect_next((next_path or "").strip())
        if nx:
            kw["login_next"] = nx
        return kw

    email_norm = _normalize_email_strict(email)
    if not email_norm:
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(error=True),
            status_code=400,
        )
    user = db.query(models.User).filter(models.User.email == email_norm).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(error=True),
            status_code=400,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(error="inactive"),
            status_code=400,
        )
    if email_verification_enabled() and not user.email_verified:
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(error="email_not_verified", email=email_norm),
            status_code=400,
        )
    token = auth.create_access_token({"sub": user.email})
    redirect_url = _safe_login_redirect_next((next_path or "").strip()) or "/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(**_access_token_cookie_args(request, token))
    _sync_viewer_tz_cookie(response, request, user)
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
        row.verified_at = None
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


@router.post("/register/verify-email-code")
def register_verify_email_code(
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    if not email_verification_enabled():
        return JSONResponse({"ok": False, "error": "disabled"}, status_code=400)
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        return JSONResponse({"ok": False, "error": "invalid_email"}, status_code=400)
    code_in = "".join(c for c in (code or "") if c.isdigit())
    if len(code_in) != 6:
        return JSONResponse({"ok": False, "error": "invalid_code"}, status_code=400)
    row = db.query(models.EmailRegistrationCode).filter(
        models.EmailRegistrationCode.email == email_norm
    ).first()
    if not row:
        return JSONResponse({"ok": False, "error": "no_code_sent"}, status_code=400)
    if datetime.utcnow() > row.expires_at:
        return JSONResponse({"ok": False, "error": "expired_code"}, status_code=400)
    if not auth.registration_codes_equal(email_norm, code_in, row.code_hash):
        return JSONResponse({"ok": False, "error": "bad_code"}, status_code=400)
    row.verified_at = datetime.utcnow()
    db.add(row)
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
    phone_number: str = Form(""),
    phone_verification_code: str = Form(""),
    ops_email_opt_in: str = Form(""),
    ops_sms_opt_in: str = Form(""),
    marketing_email_opt_in: str = Form(""),
    marketing_sms_opt_in: str = Form(""),
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

    phone_e164 = _normalize_phone_e164(phone_number)
    if (phone_number or "").strip() and not phone_e164:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "invalid_phone",
                "settings": settings,
                "email_verification": ev,
            },
            status_code=400,
        )

    phone_verified = False
    if phone_e164:
        code_in = "".join(c for c in (phone_verification_code or "") if c.isdigit())
        if len(code_in) != 6:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "no_phone_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        prow = db.query(models.PhoneRegistrationCode).filter(
            models.PhoneRegistrationCode.phone_number == phone_e164
        ).first()
        if not prow:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "no_phone_code_sent",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        if datetime.utcnow() > prow.expires_at:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "expired_phone_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        if prow.attempt_count >= 5:
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "phone_code_locked",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        if not auth.registration_codes_equal(phone_e164, code_in, prow.code_hash):
            prow.attempt_count = int(prow.attempt_count or 0) + 1
            db.add(prow)
            db.commit()
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "error": "bad_phone_code",
                    "settings": settings,
                    "email_verification": ev,
                },
                status_code=400,
            )
        prow.verified_at = datetime.utcnow()
        phone_verified = True

    email_verified = True
    if want_verify:
        email_verified = True

    # 동의는 "인증 완료 채널"만 저장
    consent_at = datetime.utcnow()
    ops_email = email_verified and _form_bool(ops_email_opt_in)
    marketing_email = email_verified and _form_bool(marketing_email_opt_in)
    ops_sms = phone_verified and _form_bool(ops_sms_opt_in)
    marketing_sms = phone_verified and _form_bool(marketing_sms_opt_in)

    new_user = models.User(
        email=email_norm,
        full_name=full_name,
        company=company or None,
        phone_number=phone_e164,
        phone_verified=phone_verified,
        phone_verified_at=(datetime.utcnow() if phone_verified else None),
        ops_email_opt_in=ops_email,
        ops_sms_opt_in=ops_sms,
        marketing_email_opt_in=marketing_email,
        marketing_sms_opt_in=marketing_sms,
        consent_updated_at=consent_at,
        hashed_password=auth.hash_password(password),
        email_verified=email_verified,
    )
    db.add(new_user)
    if phone_e164:
        prow = db.query(models.PhoneRegistrationCode).filter(
            models.PhoneRegistrationCode.phone_number == phone_e164
        ).first()
        if prow:
            db.delete(prow)
    db.commit()

    if want_verify:
        return RedirectResponse(url="/login?registered=1", status_code=302)

    token = auth.create_access_token({"sub": new_user.email})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(**_access_token_cookie_args(request, token))
    _sync_viewer_tz_cookie(response, request, new_user)
    return response


@router.post("/register/send-phone-code")
def register_send_phone_code(
    phone_number: str = Form(...),
    db: Session = Depends(get_db),
):
    phone_e164 = _normalize_phone_e164(phone_number)
    if not phone_e164:
        return JSONResponse({"ok": False, "error": "invalid_phone"}, status_code=400)

    now = datetime.utcnow()
    row = db.query(models.PhoneRegistrationCode).filter(
        models.PhoneRegistrationCode.phone_number == phone_e164
    ).first()
    if row and row.last_sent_at and (now - row.last_sent_at).total_seconds() < 60:
        return JSONResponse({"ok": False, "error": "cooldown"}, status_code=429)

    code = auth.generate_registration_otp()
    code_hash = auth.registration_code_hash(phone_e164, code)
    expires = now + timedelta(minutes=auth.registration_otp_ttl_minutes())
    try:
        send_registration_otp_sms(phone_e164, code)
    except Exception:
        logger.exception("send_registration_otp_sms failed")
        return JSONResponse({"ok": False, "error": "send_failed"}, status_code=500)

    if row:
        row.code_hash = code_hash
        row.expires_at = expires
        row.last_sent_at = now
        row.attempt_count = 0
        row.verified_at = None
    else:
        db.add(
            models.PhoneRegistrationCode(
                phone_number=phone_e164,
                code_hash=code_hash,
                expires_at=expires,
                last_sent_at=now,
                attempt_count=0,
            )
        )
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/register/verify-phone-code")
def register_verify_phone_code(
    phone_number: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    phone_e164 = _normalize_phone_e164(phone_number)
    if not phone_e164:
        return JSONResponse({"ok": False, "error": "invalid_phone"}, status_code=400)
    code_in = "".join(c for c in (code or "") if c.isdigit())
    if len(code_in) != 6:
        return JSONResponse({"ok": False, "error": "invalid_code"}, status_code=400)

    row = db.query(models.PhoneRegistrationCode).filter(
        models.PhoneRegistrationCode.phone_number == phone_e164
    ).first()
    if not row:
        return JSONResponse({"ok": False, "error": "no_code_sent"}, status_code=400)
    if datetime.utcnow() > row.expires_at:
        return JSONResponse({"ok": False, "error": "expired_code"}, status_code=400)
    if int(row.attempt_count or 0) >= 5:
        return JSONResponse({"ok": False, "error": "locked"}, status_code=429)
    if not auth.registration_codes_equal(phone_e164, code_in, row.code_hash):
        row.attempt_count = int(row.attempt_count or 0) + 1
        db.add(row)
        db.commit()
        return JSONResponse({"ok": False, "error": "bad_code"}, status_code=400)
    row.verified_at = datetime.utcnow()
    row.attempt_count = 0
    db.add(row)
    db.commit()
    return JSONResponse({"ok": True})


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


@router.get("/account", response_class=HTMLResponse)
def account_profile(request: Request, db: Session = Depends(get_db)):
    """로그인 회원의 가입 시 입력 정보 조회(비밀번호 등은 표시하지 않음)."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account", status_code=302)
    profile_saved = request.query_params.get("profile_saved") == "1"
    password_saved = request.query_params.get("password_saved") == "1"
    email_changed_ok = request.query_params.get("email_changed") == "1"
    pending_ec = (
        db.query(models.EmailChangePending)
        .filter(models.EmailChangePending.user_id == user.id)
        .first()
    )
    return templates.TemplateResponse(
        request,
        "account_profile.html",
        {
            "user": user,
            "profile_saved": profile_saved,
            "password_saved": password_saved,
            "email_changed_ok": email_changed_ok,
            "pending_email_change": pending_ec,
            "mail_for_account_actions": email_verification_enabled(),
            "deletion_grace_days": deletion_grace_days(),
        },
    )


@router.get("/account/edit", response_class=HTMLResponse)
def account_profile_edit_get(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/edit", status_code=302)
    return templates.TemplateResponse(
        request,
        "account_profile_edit.html",
        {
            "user": user,
            "full_name_value": user.full_name,
            "company_value": user.company or "",
            "timezone_value": getattr(user, "timezone", None) or "",
            "time_zones": sorted(available_timezones()),
            "error": None,
        },
    )


@router.post("/account/edit")
def account_profile_edit_post(
    request: Request,
    full_name: str = Form(...),
    company: str = Form(""),
    timezone: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/edit", status_code=302)

    tz_list = sorted(available_timezones())
    name_ok, err = _parse_profile_full_name(full_name)
    company_ok = _parse_profile_company(company)
    tz_ok, tz_err = _parse_profile_timezone(timezone)

    if err:
        return templates.TemplateResponse(
            request,
            "account_profile_edit.html",
            {
                "user": user,
                "time_zones": tz_list,
                "full_name_value": (full_name or "").strip()[:_MAX_PROFILE_FULL_NAME],
                "company_value": (company or "").strip()[:_MAX_PROFILE_COMPANY],
                "timezone_value": (timezone or "").strip()[:_MAX_VIEWER_TZ_LEN],
                "error": err,
            },
            status_code=400,
        )

    if tz_err:
        return templates.TemplateResponse(
            request,
            "account_profile_edit.html",
            {
                "user": user,
                "time_zones": tz_list,
                "full_name_value": name_ok or "",
                "company_value": (company or "").strip()[:_MAX_PROFILE_COMPANY],
                "timezone_value": (timezone or "").strip()[:_MAX_VIEWER_TZ_LEN],
                "error": tz_err,
            },
            status_code=400,
        )

    user.full_name = name_ok
    user.company = company_ok
    user.timezone = tz_ok
    db.add(user)
    db.commit()
    response = RedirectResponse(url="/account?profile_saved=1", status_code=302)
    _sync_viewer_tz_cookie(response, request, user)
    return response


@router.get("/account/password", response_class=HTMLResponse)
def account_password_get(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/password", status_code=302)
    return templates.TemplateResponse(
        request,
        "account_password.html",
        {"user": user, "error": None},
    )


@router.post("/account/password")
def account_password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/password", status_code=302)

    def _err(code: str):
        return templates.TemplateResponse(
            request,
            "account_password.html",
            {"user": user, "error": code},
            status_code=400,
        )

    if not auth.verify_password(current_password, user.hashed_password):
        return _err("wrong_current")

    np, pw_err = _parse_new_password(new_password)
    if pw_err:
        return _err(pw_err)

    if new_password.strip() != new_password_confirm.strip():
        return _err("mismatch")

    if auth.verify_password(new_password.strip(), user.hashed_password):
        return _err("same_as_current")

    user.hashed_password = auth.hash_password(np)
    db.add(user)
    db.commit()
    return RedirectResponse(url="/account?password_saved=1", status_code=302)


@router.get("/account/email", response_class=HTMLResponse)
def account_email_change_get(
    request: Request,
    db: Session = Depends(get_db),
    sent: str | None = None,
    err: str | None = None,
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/email", status_code=302)
    if getattr(user, "pending_account_deletion", False):
        return RedirectResponse(url="/account", status_code=302)
    pending = (
        db.query(models.EmailChangePending)
        .filter(models.EmailChangePending.user_id == user.id)
        .first()
    )
    return templates.TemplateResponse(
        request,
        "account_email_change.html",
        {
            "user": user,
            "pending_ec": pending,
            "sent_ok": sent == "1",
            "error": err,
            "mail_ok": email_verification_enabled(),
        },
    )


@router.post("/account/email/request")
def account_email_change_request_post(
    request: Request,
    new_email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/email", status_code=302)
    if getattr(user, "pending_account_deletion", False):
        return RedirectResponse(url="/account", status_code=302)
    if not email_verification_enabled():
        return RedirectResponse(url="/account/email?err=mail_disabled", status_code=302)

    new_norm = _normalize_email_strict(new_email)
    if not new_norm:
        return RedirectResponse(url="/account/email?err=invalid", status_code=302)
    if new_norm == (user.email or "").strip().lower():
        return RedirectResponse(url="/account/email?err=same", status_code=302)
    if db.query(models.User).filter(models.User.email == new_norm).first():
        return RedirectResponse(url="/account/email?err=duplicate", status_code=302)

    now = datetime.utcnow()
    existing = (
        db.query(models.EmailChangePending)
        .filter(models.EmailChangePending.user_id == user.id)
        .first()
    )
    if existing and (now - existing.last_sent_at).total_seconds() < 60:
        return RedirectResponse(url="/account/email?err=cooldown", status_code=302)
    if existing:
        db.delete(existing)
        db.flush()

    expires = now + timedelta(days=3)
    row = models.EmailChangePending(
        user_id=user.id,
        new_email=new_norm,
        expires_at=expires,
        last_sent_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    token = auth.create_email_change_token(row.id, new_norm)
    base = _public_base_url(request)
    confirm_url = f"{base}/account/email/confirm?token={quote(token, safe='')}"

    old_email = user.email
    _schedule_bg(send_email_change_confirm_email, new_norm, confirm_url)
    _schedule_bg(send_email_change_notice_previous, old_email, new_norm)

    return RedirectResponse(url="/account/email?sent=1", status_code=302)


@router.get("/account/email/confirm")
def account_email_confirm(request: Request, token: str = "", db: Session = Depends(get_db)):
    parsed = auth.parse_email_change_token(token)
    if not parsed:
        return RedirectResponse(url="/login?email_change_invalid=1", status_code=302)
    pid, new_norm = parsed
    row = db.query(models.EmailChangePending).filter(models.EmailChangePending.id == pid).first()
    if not row or (row.new_email or "").strip().lower() != new_norm:
        return RedirectResponse(url="/login?email_change_invalid=1", status_code=302)
    now = datetime.utcnow()
    if row.expires_at < now:
        db.delete(row)
        db.commit()
        return RedirectResponse(url="/login?email_change_invalid=1", status_code=302)

    user = db.query(models.User).filter(models.User.id == row.user_id).first()
    if (
        not user
        or not user.is_active
        or getattr(user, "pending_account_deletion", False)
    ):
        db.delete(row)
        db.commit()
        return RedirectResponse(url="/login?email_change_invalid=1", status_code=302)

    if db.query(models.User).filter(models.User.email == new_norm, models.User.id != user.id).first():
        db.delete(row)
        db.commit()
        return RedirectResponse(url="/login?email_change_invalid=1", status_code=302)

    old_email = user.email
    user.email = new_norm
    user.email_verified = True
    refresh_admin_flag_for_user(db, user)
    db.delete(row)
    db.commit()

    _schedule_bg(send_email_changed_completed_notice, old_email, new_norm)

    resp = RedirectResponse(url="/account?email_changed=1", status_code=302)
    resp.set_cookie(**_access_token_cookie_args(request, auth.create_access_token({"sub": new_norm})))
    _sync_viewer_tz_cookie(resp, request, user)
    return resp


@router.get("/account/delete", response_class=HTMLResponse)
def account_delete_confirm_get(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/delete", status_code=302)
    if getattr(user, "pending_account_deletion", False):
        return RedirectResponse(url="/account", status_code=302)
    return templates.TemplateResponse(
        request,
        "account_delete_confirm.html",
        {"user": user, "error": None, "grace_days": deletion_grace_days(), "mail_ok": email_verification_enabled()},
    )


@router.post("/account/delete/request")
def account_delete_request_post(
    request: Request,
    password: str = Form(...),
    confirm_text: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/account/delete", status_code=302)
    if getattr(user, "pending_account_deletion", False):
        return RedirectResponse(url="/account", status_code=302)

    def _form_err(code: str):
        return templates.TemplateResponse(
            request,
            "account_delete_confirm.html",
            {"user": user, "error": code, "grace_days": deletion_grace_days(), "mail_ok": email_verification_enabled()},
            status_code=400,
        )

    if (confirm_text or "").strip() != "DELETE":
        return _form_err("bad_ack")
    if not auth.verify_password(password, user.hashed_password):
        return _form_err("wrong_password")

    now = datetime.utcnow()
    grace = deletion_grace_days()
    hard_at = now + timedelta(days=grace)
    notify_email = user.email

    user.pending_account_deletion = True
    user.deletion_requested_at = now
    user.deletion_hard_scheduled_at = hard_at
    user.is_active = False
    db.query(models.EmailChangePending).filter(models.EmailChangePending.user_id == user.id).delete(
        synchronize_session=False
    )
    db.add(user)
    db.commit()

    cancel_tok = auth.create_account_delete_cancel_token(user.id)
    cancel_url = f"{_public_base_url(request)}/account/delete/cancel?token={quote(cancel_tok, safe='')}"

    if email_verification_enabled() and notify_email:
        iso = hard_at.strftime("%Y-%m-%d %H:%M UTC")
        _schedule_bg(
            send_account_deletion_started_email,
            notify_email,
            cancel_url,
            grace_days=grace,
            hard_until_iso=iso,
        )

    resp = RedirectResponse(url="/login?deletion_started=1", status_code=302)
    _delete_auth_cookie(resp, request)
    return resp


@router.get("/account/delete/cancel")
def account_delete_cancel(request: Request, token: str = "", db: Session = Depends(get_db)):
    max_age = deletion_grace_days() * 86400 + 86400
    uid = auth.parse_account_delete_cancel_token(token, max_age_sec=max_age)
    if uid is None:
        return RedirectResponse(url="/login?delete_cancel_invalid=1", status_code=302)
    user = db.query(models.User).filter(models.User.id == uid).first()
    if not user or not getattr(user, "pending_account_deletion", False):
        return RedirectResponse(url="/login?delete_cancel_invalid=1", status_code=302)

    user.pending_account_deletion = False
    user.deletion_requested_at = None
    user.deletion_hard_scheduled_at = None
    user.is_active = True
    db.add(user)
    db.commit()
    return RedirectResponse(url="/login?delete_cancelled=1", status_code=302)


@router.get("/logout")
def logout(request: Request):
    try:
        request.session.clear()
    except Exception:
        pass
    response = RedirectResponse(url="/", status_code=302)
    _delete_auth_cookie(response, request)
    _delete_viewer_tz_cookie(response, request)
    return response
