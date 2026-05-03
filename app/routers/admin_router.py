from fastapi import APIRouter, Body, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, auth
from ..codelib_reference_import import build_reference_payload_dict_from_abap_code
from ..account_lifecycle import purge_user_and_owned_data as lifecycle_purge_user
from ..database import get_db
from ..templates_config import templates
from ..writing_guides_service import LOGICAL_KEYS, save_writing_guide_bilingual

router = APIRouter(prefix="/admin")


def _require_admin(request: Request, db: Session):
    user = auth.get_current_user(request, db)
    if not user or not user.is_admin:
        return None
    return user


def _admin_purge_user_and_data(db: Session, target: models.User, actor: models.User) -> str | None:
    """테스트/운영: 사용자와 소유 데이터 영구 삭제."""
    if target.id == actor.id:
        return "self"
    lifecycle_purge_user(db, target.id)
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


@router.post("/users/{user_id}/purge-now")
def admin_user_purge_now(user_id: int, request: Request, db: Session = Depends(get_db)):
    """탈퇴 유예 중인 계정을 즉시 영구 삭제(관리자)."""
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    if target.id == actor.id:
        return RedirectResponse(url="/admin/users?err=self", status_code=302)
    if not getattr(target, "pending_account_deletion", False):
        return RedirectResponse(url="/admin/users?err=not_pending", status_code=302)
    lifecycle_purge_user(db, target.id)
    return RedirectResponse(url="/admin/users?deleted=1", status_code=302)


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
    usage: str = Form("abap"),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    code = code.strip()
    u = (usage or "abap").strip().lower()
    if u not in ("abap", "integration", "both"):
        u = "abap"
    if code and not db.query(models.DevType).filter(models.DevType.code == code).first():
        max_order = db.query(models.DevType).count()
        db.add(
            models.DevType(
                code=code,
                label_ko=label_ko.strip(),
                label_en=label_en.strip(),
                sort_order=max_order,
                usage=u,
            )
        )
        db.commit()
    return RedirectResponse(url="/admin/devtypes", status_code=302)


@router.post("/devtypes/{dt_id}/usage")
def admin_devtype_usage(dt_id: int, request: Request, usage: str = Form(...), db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    d = db.query(models.DevType).filter(models.DevType.id == dt_id).first()
    if d:
        u = (usage or "abap").strip().lower()
        if u in ("abap", "integration", "both"):
            d.usage = u
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
    ("service_abap_intro_md_ko", "신규 개발(SAP ABAP) 첫 페이지 소개 (Markdown)"),
    ("service_analysis_intro_md_ko", "분석·개선 첫 페이지 소개 (Markdown)"),
    ("service_integration_intro_md_ko", "연동 개발 첫 페이지 소개 (Markdown)"),
    ("terms_of_service", "이용약관"),
    ("privacy_policy", "개인정보처리방침"),
]

HOME_TILE_API_KEYS = [
    "home_tile_guide_title_ko",
    "home_tile_guide_title_en",
    "home_tile_guide_desc_ko",
    "home_tile_guide_desc_en",
    "home_tile_abap_title_ko",
    "home_tile_abap_title_en",
    "home_tile_abap_desc_ko",
    "home_tile_abap_desc_en",
    "home_tile_analysis_title_ko",
    "home_tile_analysis_title_en",
    "home_tile_analysis_desc_ko",
    "home_tile_analysis_desc_en",
    "home_tile_integration_title_ko",
    "home_tile_integration_title_en",
    "home_tile_integration_desc_ko",
    "home_tile_integration_desc_en",
    "user_guide_pdf_url",
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


@router.patch("/api/home-tiles")
async def admin_patch_home_tiles(request: Request, db: Session = Depends(get_db)):
    actor = _require_admin(request, db)
    if not actor:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid_body"}, status_code=400)
    for key in HOME_TILE_API_KEYS:
        if key not in body:
            continue
        raw = body[key]
        val = "" if raw is None else str(raw).strip()
        existing = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
        if existing:
            existing.value = val
        else:
            db.add(models.SiteSettings(key=key, value=val))
    db.commit()
    return JSONResponse({"ok": True})


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


# ── 작성 가이드 인라인 저장 (관리자, JSON) ────────────────────────────

@router.post("/api/writing-guide")
async def admin_api_writing_guide_save(
    request: Request,
    db: Session = Depends(get_db),
    payload: dict = Body(...),
):
    """요청 폼에서 관리자가 작성 가이드(한/영 HTML)를 저장할 때 사용."""
    user = _require_admin(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    key = (payload.get("key") or "").strip()
    if key not in LOGICAL_KEYS:
        return JSONResponse({"ok": False, "error": "invalid_key"}, status_code=400)
    try:
        save_writing_guide_bilingual(
            db,
            logical_key=key,
            html_ko=payload.get("html_ko"),
            html_en=payload.get("html_en"),
        )
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid_key"}, status_code=400)
    return {"ok": True}


# ── 코드 갤러리 → 참고 코드 가져오기(단건) API ─────────────────────────

@router.get("/api/codelib-items")
def admin_api_codelib_items(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=200),
):
    """관리자 전용: 갤러리(abap_codes) 목록 요약."""
    user = _require_admin(request, db)
    if not user:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    query = db.query(models.ABAPCode).order_by(models.ABAPCode.id.desc())
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        query = query.filter(
            or_(
                models.ABAPCode.title.ilike(like),
                models.ABAPCode.program_id.ilike(like),
                models.ABAPCode.transaction_code.ilike(like),
            )
        )
    rows = query.limit(100).all()
    return {
        "items": [
            {
                "id": r.id,
                "title": (r.title or "")[:200],
                "program_id": (r.program_id or "")[:40],
                "transaction_code": (r.transaction_code or "")[:20],
                "is_draft": bool(r.is_draft),
            }
            for r in rows
        ],
    }


@router.get("/api/codelib-items/{item_id}/reference-payload")
def admin_api_codelib_item_reference_payload(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """관리자 전용: 갤러리 1건을 참고 코드 JSON 스키마로 변환."""
    user = _require_admin(request, db)
    if not user:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    code = db.query(models.ABAPCode).filter(models.ABAPCode.id == item_id).first()
    if not code:
        return JSONResponse({"error": "not_found"}, status_code=404)
    payload = build_reference_payload_dict_from_abap_code(code)
    if payload is None:
        return JSONResponse({"error": "reference_code_too_large"}, status_code=400)
    return {"payload": payload}
