from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..templates_config import templates

router = APIRouter(prefix="/admin")


def _require_admin(request: Request, db: Session):
    user = auth.get_current_user(request, db)
    if not user or not user.is_admin:
        return None
    return user


def _admin_purge_user_and_data(db: Session, target: models.User, actor: models.User) -> str | None:
    """
    테스트용: 사용자와 소유 RFP·코드·이용후기 등 연관 데이터 삭제.
    성공 시 None, 실패 시 오류 코드 문자열 (redirect query용).
    """
    if target.id == actor.id:
        return "self"
    uid = target.id
    for rfp in db.query(models.RFP).filter(models.RFP.user_id == uid).all():
        db.query(models.RFPMessage).filter(models.RFPMessage.rfp_id == rfp.id).delete()
        db.delete(rfp)
    db.query(models.ABAPCode).filter(models.ABAPCode.uploaded_by == uid).delete()
    rev_ids = [r.id for r in db.query(models.Review).filter(models.Review.user_id == uid).all()]
    if rev_ids:
        db.query(models.ReviewComment).filter(models.ReviewComment.review_id.in_(rev_ids)).delete(
            synchronize_session=False
        )
    db.query(models.Review).filter(models.Review.user_id == uid).delete(synchronize_session=False)
    db.query(models.ReviewComment).filter(models.ReviewComment.user_id == uid).delete(
        synchronize_session=False
    )
    db.delete(target)
    db.commit()
    return None


# ── 관리자 대시보드 ────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "admin/dashboard.html", {"request": request, "user": user})


# ── 사용자 삭제 (테스트용: 동일 이메일 재가입) ───────────

@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    db: Session = Depends(get_db),
    deleted: str | None = None,
    err: str | None = None,
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "deleted": deleted == "1",
            "err": err,
        },
    )


@router.post("/users/{user_id}/delete")
def admin_user_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    code = _admin_purge_user_and_data(db, target, actor)
    if code == "self":
        return RedirectResponse(url="/admin/users?err=self", status_code=302)
    return RedirectResponse(url="/admin/users?deleted=1", status_code=302)


# ── SAP 모듈 관리 ──────────────────────────────────────

@router.get("/modules", response_class=HTMLResponse)
def admin_modules(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    modules = db.query(models.SAPModule).order_by(models.SAPModule.sort_order).all()
    return templates.TemplateResponse(request, "admin/modules.html", {"request": request, "user": user, "modules": modules})


@router.post("/modules/add")
def admin_module_add(
    request: Request,
    code: str = Form(...),
    label_ko: str = Form(...),
    label_en: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    code = code.strip().upper()
    if code and not db.query(models.SAPModule).filter(models.SAPModule.code == code).first():
        max_order = db.query(models.SAPModule).count()
        db.add(models.SAPModule(code=code, label_ko=label_ko.strip(), label_en=label_en.strip(), sort_order=max_order))
        db.commit()
    return RedirectResponse(url="/admin/modules", status_code=302)


@router.post("/modules/{mod_id}/toggle")
def admin_module_toggle(mod_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    m = db.query(models.SAPModule).filter(models.SAPModule.id == mod_id).first()
    if m:
        m.is_active = not m.is_active
        db.commit()
    return RedirectResponse(url="/admin/modules", status_code=302)


@router.post("/modules/{mod_id}/delete")
def admin_module_delete(mod_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    m = db.query(models.SAPModule).filter(models.SAPModule.id == mod_id).first()
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse(url="/admin/modules", status_code=302)


# ── 개발 유형 관리 ─────────────────────────────────────

@router.get("/devtypes", response_class=HTMLResponse)
def admin_devtypes(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    devtypes = db.query(models.DevType).order_by(models.DevType.sort_order).all()
    return templates.TemplateResponse(request, "admin/devtypes.html", {"request": request, "user": user, "devtypes": devtypes})


@router.post("/devtypes/add")
def admin_devtype_add(
    request: Request,
    code: str = Form(...),
    label_ko: str = Form(...),
    label_en: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    code = code.strip()
    if code and not db.query(models.DevType).filter(models.DevType.code == code).first():
        max_order = db.query(models.DevType).count()
        db.add(models.DevType(code=code, label_ko=label_ko.strip(), label_en=label_en.strip(), sort_order=max_order))
        db.commit()
    return RedirectResponse(url="/admin/devtypes", status_code=302)


@router.post("/devtypes/{dt_id}/toggle")
def admin_devtype_toggle(dt_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    d = db.query(models.DevType).filter(models.DevType.id == dt_id).first()
    if d:
        d.is_active = not d.is_active
        db.commit()
    return RedirectResponse(url="/admin/devtypes", status_code=302)


@router.post("/devtypes/{dt_id}/delete")
def admin_devtype_delete(dt_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    d = db.query(models.DevType).filter(models.DevType.id == dt_id).first()
    if d:
        db.delete(d)
        db.commit()
    return RedirectResponse(url="/admin/devtypes", status_code=302)


# ── 사이트 설정 관리 ────────────────────────────────────

SITE_SETTING_KEYS = [
    ("home_headline_ko", "홈 헤드라인 (한국어)"),
    ("home_headline_en", "홈 헤드라인 (English)"),
    ("home_subtitle_ko", "홈 부제목 (한국어)"),
    ("home_subtitle_en", "홈 부제목 (English)"),
    ("rfp_writing_tip", "개발 요청 작성 팁"),
    ("terms_of_service", "이용약관"),
    ("privacy_policy", "개인정보처리방침"),
]


@router.get("/settings", response_class=HTMLResponse)
def admin_settings(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    return templates.TemplateResponse(request, "admin/settings.html", {
        "request": request, "user": user,
        "settings": raw, "setting_keys": SITE_SETTING_KEYS,
    })


@router.post("/settings")
async def admin_settings_save(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    for key, _ in SITE_SETTING_KEYS:
        val = (form.get(key) or "").strip()
        existing = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
        if existing:
            existing.value = val
        else:
            db.add(models.SiteSettings(key=key, value=val))
    db.commit()
    return RedirectResponse(url="/admin/settings?saved=1", status_code=302)


# ── 공지사항 관리 ───────────────────────────────────────

@router.get("/notices", response_class=HTMLResponse)
def admin_notices(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    notices = db.query(models.Notice).order_by(models.Notice.created_at.desc()).all()
    return templates.TemplateResponse(request, "admin/notices.html", {
        "request": request, "user": user, "notices": notices,
    })


@router.post("/notices/add")
def admin_notice_add(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    db.add(models.Notice(title=title.strip(), content=content.strip()))
    db.commit()
    return RedirectResponse(url="/admin/notices", status_code=302)


@router.post("/notices/{notice_id}/toggle")
def admin_notice_toggle(notice_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    n = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if n:
        n.is_active = not n.is_active
        db.commit()
    return RedirectResponse(url="/admin/notices", status_code=302)


@router.post("/notices/{notice_id}/delete")
def admin_notice_delete(notice_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    n = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if n:
        db.delete(n)
        db.commit()
    return RedirectResponse(url="/admin/notices", status_code=302)


# ── FAQ 관리 ────────────────────────────────────────────

@router.get("/faqs", response_class=HTMLResponse)
def admin_faqs(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    faqs = db.query(models.FAQ).order_by(models.FAQ.sort_order).all()
    return templates.TemplateResponse(request, "admin/faqs.html", {
        "request": request, "user": user, "faqs": faqs,
    })


@router.post("/faqs/add")
def admin_faq_add(
    request: Request,
    question: str = Form(...),
    answer: str = Form(...),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    db.add(models.FAQ(question=question.strip(), answer=answer.strip(), sort_order=sort_order))
    db.commit()
    return RedirectResponse(url="/admin/faqs", status_code=302)


@router.post("/faqs/{faq_id}/toggle")
def admin_faq_toggle(faq_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    f = db.query(models.FAQ).filter(models.FAQ.id == faq_id).first()
    if f:
        f.is_active = not f.is_active
        db.commit()
    return RedirectResponse(url="/admin/faqs", status_code=302)


@router.post("/faqs/{faq_id}/delete")
def admin_faq_delete(faq_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    f = db.query(models.FAQ).filter(models.FAQ.id == faq_id).first()
    if f:
        db.delete(f)
        db.commit()
    return RedirectResponse(url="/admin/faqs", status_code=302)


# ── 이용후기 관리 (Admin 공개 승인) ─────────────────────

@router.get("/reviews", response_class=HTMLResponse)
def admin_reviews(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    reviews = db.query(models.Review).order_by(models.Review.created_at.desc()).all()
    return templates.TemplateResponse(request, "admin/reviews.html", {
        "request": request, "user": user, "reviews": reviews,
    })


@router.post("/reviews/{review_id}/toggle")
def admin_review_toggle(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    r = db.query(models.Review).filter(models.Review.id == review_id).first()
    if r:
        r.is_public = not r.is_public
        db.commit()
    return RedirectResponse(url="/admin/reviews", status_code=302)


@router.post("/reviews/{review_id}/delete")
def admin_review_delete(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    r = db.query(models.Review).filter(models.Review.id == review_id).first()
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse(url="/admin/reviews", status_code=302)
