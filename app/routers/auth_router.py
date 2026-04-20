from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..templates_config import templates

router = APIRouter()


def _normalize_email_strict(raw: str) -> str | None:
    """RFC 기반 구문 검증(가장 흔한 방식). DNS MX 조회는 배포 환경에 따라 생략."""
    try:
        validated = validate_email(raw.strip(), check_deliverability=False)
        return validated.normalized
    except EmailNotValidError:
        return None


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
def login_page(request: Request):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


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
    token = auth.create_access_token({"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
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
    return templates.TemplateResponse(request, "register.html", {"settings": settings})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    company: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = _normalize_email_strict(email)
    if not email_norm:
        settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "invalid_email", "settings": settings},
            status_code=400,
        )

    existing = db.query(models.User).filter(models.User.email == email_norm).first()
    if existing:
        settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "duplicate", "settings": settings},
            status_code=400,
        )
    new_user = models.User(
        email=email_norm,
        full_name=full_name,
        company=company or None,
        hashed_password=auth.hash_password(password),
    )
    db.add(new_user)
    db.commit()
    token = auth.create_access_token({"sub": new_user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(**_access_token_cookie_args(request, token))
    return response


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
