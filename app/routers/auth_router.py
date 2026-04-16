import re
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db
from ..templates_config import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": True},
            status_code=400,
        )
    token = auth.create_access_token({"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("access_token", token, httponly=True, max_age=86400)
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
    return templates.TemplateResponse("register.html", {"request": request, "settings": settings})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    company: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "duplicate"},
            status_code=400,
        )
    new_user = models.User(
        email=email,
        full_name=full_name,
        company=company or None,
        hashed_password=auth.hash_password(password),
    )
    db.add(new_user)
    db.commit()
    token = auth.create_access_token({"sub": new_user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("access_token", token, httponly=True, max_age=86400)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response
