import os
from io import BytesIO
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, Request, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from .. import models, auth, r2_storage
from ..codelib_reference_import import build_reference_payload_dict_from_abap_code
from ..account_lifecycle import purge_user_and_owned_data as lifecycle_purge_user
from ..database import get_db
from ..templates_config import templates
from ..writing_guides_service import LOGICAL_KEYS, save_writing_guide_bilingual
from ..email_smtp import send_consultant_approved_email
from ..review_ratings_util import rating_aggregates_for_reviews
from ..subscription_catalog import (
    DEFAULT_PLAN_MONTHLY_PRICES,
    METRIC_LABEL_KO,
    METRIC_ORDER,
    SUBSCRIPTION_METRIC_HELP_KEY_PREFIX,
    format_monthly_krw_display,
    format_monthly_usd_display,
)
from ..subscription_quota import SUBSCRIPTION_SOURCE_ADMIN, utc_year_month
from ..i18n_overrides import build_admin_grouped, invalidate_en_overrides_cache, load_i18n_baseline
from ..i18n_admin_suggest import suggest_ui_english

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


def _admin_users_rows_and_summary(
    db: Session,
    qq: str,
    verified: str,
    pending: str,
    user_kind: str,
) -> tuple[list[dict], dict]:
    """회원 현황 표와 동일 필터·집계로 rows / summary 생성."""
    q_users = db.query(models.User)
    if qq:
        like = f"%{qq}%"
        q_users = q_users.filter(
            or_(
                models.User.email.ilike(like),
                models.User.full_name.ilike(like),
                models.User.company.ilike(like),
            )
        )
    if verified == "y":
        q_users = q_users.filter(models.User.email_verified.is_(True))
    elif verified == "n":
        q_users = q_users.filter(models.User.email_verified.is_(False))

    if pending == "y":
        q_users = q_users.filter(models.User.pending_account_deletion.is_(True))
    elif pending == "n":
        q_users = q_users.filter(models.User.pending_account_deletion.is_(False))

    if user_kind == "admin":
        q_users = q_users.filter(models.User.is_admin.is_(True))
    elif user_kind == "consultant":
        q_users = q_users.filter(models.User.is_admin.is_(False), models.User.is_consultant.is_(True))
    elif user_kind == "member":
        q_users = q_users.filter(models.User.is_admin.is_(False), models.User.is_consultant.is_(False))

    users = q_users.order_by(models.User.id.desc()).all()
    user_ids = [u.id for u in users]

    rfp_counts: dict[int, int] = {}
    rfp_submitted_counts: dict[int, int] = {}
    rfp_delivery_counts: dict[int, int] = {}
    rfp_paid_active_counts: dict[int, int] = {}
    integration_counts: dict[int, int] = {}
    abap_analysis_counts: dict[int, int] = {}

    if user_ids:
        for uid, n in (
            db.query(models.RFP.user_id, func.count(models.RFP.id))
            .filter(models.RFP.user_id.in_(user_ids))
            .group_by(models.RFP.user_id)
            .all()
        ):
            rfp_counts[int(uid)] = int(n or 0)
        for uid, n in (
            db.query(models.RFP.user_id, func.count(models.RFP.id))
            .filter(
                models.RFP.user_id.in_(user_ids),
                models.RFP.status != "draft",
            )
            .group_by(models.RFP.user_id)
            .all()
        ):
            rfp_submitted_counts[int(uid)] = int(n or 0)
        for uid, n in (
            db.query(models.RFP.user_id, func.count(models.RFP.id))
            .filter(
                models.RFP.user_id.in_(user_ids),
                or_(
                    models.RFP.fs_status.in_(("generating", "ready")),
                    models.RFP.delivered_code_status.in_(("generating", "ready")),
                ),
            )
            .group_by(models.RFP.user_id)
            .all()
        ):
            rfp_delivery_counts[int(uid)] = int(n or 0)
        for uid, n in (
            db.query(models.RFP.user_id, func.count(models.RFP.id))
            .filter(
                models.RFP.user_id.in_(user_ids),
                models.RFP.paid_engagement_status == "active",
            )
            .group_by(models.RFP.user_id)
            .all()
        ):
            rfp_paid_active_counts[int(uid)] = int(n or 0)
        for uid, n in (
            db.query(models.IntegrationRequest.user_id, func.count(models.IntegrationRequest.id))
            .filter(models.IntegrationRequest.user_id.in_(user_ids))
            .group_by(models.IntegrationRequest.user_id)
            .all()
        ):
            integration_counts[int(uid)] = int(n or 0)
        for uid, n in (
            db.query(models.AbapAnalysisRequest.user_id, func.count(models.AbapAnalysisRequest.id))
            .filter(models.AbapAnalysisRequest.user_id.in_(user_ids))
            .group_by(models.AbapAnalysisRequest.user_id)
            .all()
        ):
            abap_analysis_counts[int(uid)] = int(n or 0)

    rows: list[dict] = []
    for u in users:
        uid = int(u.id)
        row = {
            "user": u,
            "rfp_count": rfp_counts.get(uid, 0),
            "rfp_submitted_count": rfp_submitted_counts.get(uid, 0),
            "rfp_delivery_count": rfp_delivery_counts.get(uid, 0),
            "rfp_paid_active_count": rfp_paid_active_counts.get(uid, 0),
            "integration_count": integration_counts.get(uid, 0),
            "abap_analysis_count": abap_analysis_counts.get(uid, 0),
        }
        row["total_activity_count"] = (
            row["rfp_count"] + row["integration_count"] + row["abap_analysis_count"]
        )
        rows.append(row)

    total_users = db.query(func.count(models.User.id)).scalar() or 0
    verified_users = db.query(func.count(models.User.id)).filter(models.User.email_verified.is_(True)).scalar() or 0
    pending_users = (
        db.query(func.count(models.User.id))
        .filter(models.User.pending_account_deletion.is_(True))
        .scalar()
        or 0
    )
    active_paid_members = (
        db.query(func.count(func.distinct(models.RFP.user_id)))
        .filter(models.RFP.paid_engagement_status == "active")
        .scalar()
        or 0
    )
    members_with_rfp = (
        db.query(func.count(func.distinct(models.RFP.user_id))).scalar() or 0
    )
    members_with_any_activity = (
        db.query(func.count(func.distinct(models.User.id)))
        .outerjoin(models.RFP, models.RFP.user_id == models.User.id)
        .outerjoin(models.IntegrationRequest, models.IntegrationRequest.user_id == models.User.id)
        .outerjoin(models.AbapAnalysisRequest, models.AbapAnalysisRequest.user_id == models.User.id)
        .filter(
            or_(
                models.RFP.id.isnot(None),
                models.IntegrationRequest.id.isnot(None),
                models.AbapAnalysisRequest.id.isnot(None),
            )
        )
        .scalar()
        or 0
    )
    summary = {
        "total_users": int(total_users),
        "verified_users": int(verified_users),
        "pending_users": int(pending_users),
        "active_paid_members": int(active_paid_members),
        "members_with_rfp": int(members_with_rfp),
        "members_with_any_activity": int(members_with_any_activity),
        "visible_users": len(users),
    }
    return rows, summary


@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    db: Session = Depends(get_db),
    deleted: str | None = None,
    err: str | None = None,
    q: str | None = Query(default=None),
    verified: str = Query(default="all"),
    pending: str = Query(default="all"),
    user_kind: str = Query(default="all"),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    qq = (q or "").strip()
    rows, summary = _admin_users_rows_and_summary(db, qq, verified, pending, user_kind)

    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "deleted": deleted == "1",
            "err": err,
            "summary": summary,
            "q": qq,
            "verified": verified,
            "pending": pending,
            "user_kind": user_kind,
        },
    )


@router.get("/users/export.xlsx")
def admin_users_export_xlsx(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    verified: str = Query(default="all"),
    pending: str = Query(default="all"),
    user_kind: str = Query(default="all"),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)

    qq = (q or "").strip()
    rows, _summary = _admin_users_rows_and_summary(db, qq, verified, pending, user_kind)

    wb = Workbook()
    ws = wb.active
    ws.title = "users"
    headers = [
        "ID",
        "이메일",
        "이름",
        "회사",
        "관리자",
        "컨설턴트",
        "이메일인증",
        "휴대폰",
        "휴대폰인증",
        "가입일(UTC)",
        "구독플랜",
        "탈퇴유예",
        "RFP",
        "RFP제출",
        "RFP납품단계",
        "유료활성RFP",
        "연동",
        "ABAP분석",
        "총활동",
        "컨설턴트프로필첨부",
    ]
    ws.append(headers)

    for row in rows:
        u = row["user"]
        if u.is_admin:
            cons = "관리자"
        elif u.is_consultant:
            cons = "Y"
        elif getattr(u, "consultant_application_pending", False):
            cons = "신청중"
        else:
            cons = "N"
        created = u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else ""
        plan = (getattr(u, "subscription_plan_code", None) or "") or ""
        phone = (getattr(u, "phone_number", None) or "") or ""
        phone_v = "Y" if getattr(u, "phone_verified", False) else "N"
        has_prof = "Y" if getattr(u, "consultant_profile_file_path", None) else "N"
        ws.append(
            [
                u.id,
                u.email or "",
                u.full_name or "",
                u.company or "",
                "Y" if u.is_admin else "N",
                cons,
                "Y" if u.email_verified else "N",
                phone,
                phone_v,
                created,
                plan,
                "Y" if getattr(u, "pending_account_deletion", False) else "N",
                row["rfp_count"],
                row["rfp_submitted_count"],
                row["rfp_delivery_count"],
                row["rfp_paid_active_count"],
                row["integration_count"],
                row["abap_analysis_count"],
                row["total_activity_count"],
                has_prof,
            ]
        )

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = f"users_export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content=bio.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/users/{user_id}/consultant-toggle")
def admin_user_toggle_consultant(user_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    if target.is_admin:
        return RedirectResponse(url="/admin/users?err=admin_consultant", status_code=302)
    was_consultant = bool(getattr(target, "is_consultant", False))
    was_pending = bool(getattr(target, "consultant_application_pending", False))
    target.is_consultant = not was_consultant
    if target.is_consultant:
        target.consultant_application_pending = False
    else:
        target.consultant_application_pending = False
    db.commit()
    if (not was_consultant) and target.is_consultant and was_pending:
        try:
            send_consultant_approved_email(target.email)
        except Exception:
            pass
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/users/{user_id}/consultant-profile/download")
def admin_user_consultant_profile_download(user_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    path = (getattr(target, "consultant_profile_file_path", None) or "").strip()
    fname = (getattr(target, "consultant_profile_file_name", None) or "consultant_profile").strip() or "consultant_profile"
    if not path:
        return RedirectResponse(url="/admin/users", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url="/admin/users", status_code=302)
        url = r2_storage.presigned_get_url(ref, fname)
        return RedirectResponse(url=url, status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url="/admin/users", status_code=302)
    return FileResponse(ref, filename=fname)


def _parse_admin_optional_utc_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip().replace("Z", "")
    if not s:
        return None
    if "T" in s:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return None
    if len(s) >= 16:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


@router.get("/users/{user_id}/subscription", response_class=HTMLResponse)
def admin_user_subscription_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    kind = "consultant" if target.is_consultant else "member"
    plans = (
        db.query(models.SubscriptionPlan)
        .filter(
            models.SubscriptionPlan.account_kind == kind,
            models.SubscriptionPlan.is_active.is_(True),
        )
        .order_by(models.SubscriptionPlan.sort_order, models.SubscriptionPlan.id)
        .all()
    )
    ym = utc_year_month()
    usage_rows = (
        db.query(models.SubscriptionUsageMonthly)
        .filter(
            models.SubscriptionUsageMonthly.user_id == target.id,
            models.SubscriptionUsageMonthly.year_month == ym,
        )
        .all()
    )
    usage_map = {r.metric_key: int(r.used) for r in usage_rows}
    return templates.TemplateResponse(
        request,
        "admin/user_subscription.html",
        {
            "request": request,
            "user": actor,
            "target": target,
            "plans": plans,
            "usage_map": usage_map,
            "usage_year_month": ym,
            "metric_order": METRIC_ORDER,
            "metric_label_ko": METRIC_LABEL_KO,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/users/{user_id}/subscription")
def admin_user_subscription_save(
    user_id: int,
    request: Request,
    subscription_plan_code: str = Form(""),
    clear_plan_expires: str = Form("0"),
    plan_expires_at: str = Form(""),
    clear_trial: str = Form("0"),
    trial_ends_at: str = Form(""),
    usage_metric: str = Form(""),
    usage_set_used: str = Form(""),
    db: Session = Depends(get_db),
):
    actor = _require_admin(request, db)
    if not actor:
        return RedirectResponse(url="/", status_code=302)
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users", status_code=302)
    code = (subscription_plan_code or "").strip()[:32] or "experience"
    target.subscription_plan_code = code
    target.subscription_plan_source = SUBSCRIPTION_SOURCE_ADMIN
    if (clear_plan_expires or "").strip() == "1":
        target.subscription_plan_expires_at = None
    else:
        pdt = _parse_admin_optional_utc_datetime(plan_expires_at)
        if pdt:
            target.subscription_plan_expires_at = pdt
    if (clear_trial or "").strip() == "1":
        target.experience_trial_ends_at = None
    else:
        tdt = _parse_admin_optional_utc_datetime(trial_ends_at)
        if tdt:
            target.experience_trial_ends_at = tdt

    mk = (usage_metric or "").strip()
    su = (usage_set_used or "").strip()
    if mk and su.isdigit():
        used_v = max(0, int(su))
        ym = utc_year_month()
        row = (
            db.query(models.SubscriptionUsageMonthly)
            .filter(
                models.SubscriptionUsageMonthly.user_id == target.id,
                models.SubscriptionUsageMonthly.metric_key == mk,
                models.SubscriptionUsageMonthly.year_month == ym,
            )
            .first()
        )
        if row is None:
            db.add(
                models.SubscriptionUsageMonthly(
                    user_id=target.id,
                    metric_key=mk,
                    year_month=ym,
                    used=used_v,
                )
            )
        else:
            row.used = used_v
    db.commit()
    return RedirectResponse(url=f"/admin/users/{user_id}/subscription?saved=1", status_code=302)


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
    notices = (
        db.query(models.Notice)
        .order_by(models.Notice.sort_order.asc(), models.Notice.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(request, "admin/notices.html", {
        "request": request, "user": user, "notices": notices,
    })


@router.post("/notices/add")
def admin_notice_add(
    request: Request,
    title: str = Form(...),
    title_en: str = Form(""),
    content: str = Form(""),
    content_en: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    te = (title_en or "").strip() or None
    ce = (content_en or "").strip() or None
    db.add(
        models.Notice(
            title=title.strip(),
            title_en=te,
            content=(content or "").strip(),
            content_en=ce,
            sort_order=max(0, int(sort_order)),
        )
    )
    db.commit()
    return RedirectResponse(url="/admin/notices", status_code=302)


@router.post("/notices/add-bulk")
async def admin_notice_add_bulk(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    n_saved = 0
    for i in range(10):
        title = (form.get(f"title_{i}") or "").strip()
        if not title:
            continue
        content = (form.get(f"content_{i}") or "").strip()
        try:
            so = int(form.get(f"sort_order_{i}") or 0)
        except (TypeError, ValueError):
            so = 0
        te = (form.get(f"title_en_{i}") or "").strip() or None
        ce = (form.get(f"content_en_{i}") or "").strip() or None
        db.add(
            models.Notice(
                title=title,
                title_en=te,
                content=content,
                content_en=ce,
                sort_order=max(0, so),
            )
        )
        n_saved += 1
    if n_saved:
        db.commit()
    return RedirectResponse(url=f"/admin/notices?bulk_saved={n_saved}", status_code=303)


@router.post("/notices/{notice_id}/update")
def admin_notice_update(
    notice_id: int,
    request: Request,
    title: str = Form(...),
    title_en: str = Form(""),
    content: str = Form(""),
    content_en: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    n = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if n:
        n.title = title.strip()
        n.title_en = (title_en or "").strip() or None
        n.content = (content or "").strip()
        n.content_en = (content_en or "").strip() or None
        n.sort_order = max(0, int(sort_order))
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
    faqs = (
        db.query(models.FAQ)
        .order_by(models.FAQ.sort_order.asc(), models.FAQ.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(request, "admin/faqs.html", {
        "request": request, "user": user, "faqs": faqs,
    })


@router.post("/faqs/add")
def admin_faq_add(
    request: Request,
    question: str = Form(...),
    question_en: str = Form(""),
    answer: str = Form(...),
    answer_en: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    qe = (question_en or "").strip() or None
    ae = (answer_en or "").strip() or None
    db.add(
        models.FAQ(
            question=question.strip(),
            question_en=qe,
            answer=(answer or "").strip(),
            answer_en=ae,
            sort_order=max(0, int(sort_order)),
        )
    )
    db.commit()
    return RedirectResponse(url="/admin/faqs", status_code=302)


@router.post("/faqs/add-bulk")
async def admin_faq_add_bulk(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    n_saved = 0
    for i in range(10):
        question = (form.get(f"question_{i}") or "").strip()
        answer = (form.get(f"answer_{i}") or "").strip()
        if not question or not answer:
            continue
        try:
            so = int(form.get(f"sort_order_{i}") or 0)
        except (TypeError, ValueError):
            so = 0
        qe = (form.get(f"question_en_{i}") or "").strip() or None
        ae = (form.get(f"answer_en_{i}") or "").strip() or None
        db.add(
            models.FAQ(
                question=question,
                question_en=qe,
                answer=answer,
                answer_en=ae,
                sort_order=max(0, so),
            )
        )
        n_saved += 1
    if n_saved:
        db.commit()
    return RedirectResponse(url=f"/admin/faqs?bulk_saved={n_saved}", status_code=303)


@router.post("/faqs/{faq_id}/update")
def admin_faq_update(
    faq_id: int,
    request: Request,
    question: str = Form(...),
    question_en: str = Form(""),
    answer: str = Form(...),
    answer_en: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    f = db.query(models.FAQ).filter(models.FAQ.id == faq_id).first()
    if f:
        f.question = question.strip()
        f.question_en = (question_en or "").strip() or None
        f.answer = (answer or "").strip()
        f.answer_en = (answer_en or "").strip() or None
        f.sort_order = max(0, int(sort_order))
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


# ── 문의/리뷰 전체 모니터링 (관리자 비노출·삭제) ─────────────────────

@router.get("/reviews", response_class=HTMLResponse)
def admin_reviews(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    reviews = (
        db.query(models.Review)
        .options(joinedload(models.Review.author), joinedload(models.Review.comments))
        .order_by(models.Review.created_at.desc())
        .all()
    )
    rating_meta = rating_aggregates_for_reviews(db, [r.id for r in reviews])
    return templates.TemplateResponse(request, "admin/reviews.html", {
        "request": request, "user": user, "reviews": reviews, "rating_meta": rating_meta,
    })


@router.post("/reviews/{review_id}/suppress")
def admin_review_suppress(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    r = db.query(models.Review).filter(models.Review.id == review_id).first()
    if r:
        r.admin_suppressed = not bool(r.admin_suppressed)
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
    """요청 폼에서 관리자가 작성 가이드(한/영 Markdown)를 저장할 때 사용."""
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
            md_ko=payload.get("md_ko") if payload.get("md_ko") is not None else payload.get("html_ko"),
            md_en=payload.get("md_en") if payload.get("md_en") is not None else payload.get("html_en"),
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


# ── 구독 플랜(안내 문구 · 추후 권한/한도 확장) ─────────────────

def _parse_optional_krw_val(raw) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_optional_usd_to_cents(raw) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
        return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


SUBSCRIPTION_PLAN_NOTICE_KEYS = (
    "subscription_plans_notice_md_ko",
    "subscription_plans_notice_md_en",
)


@router.get("/subscription-plans", response_class=HTMLResponse)
def admin_subscription_plans_settings(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    plans = (
        db.query(models.SubscriptionPlan)
        .options(joinedload(models.SubscriptionPlan.entitlements))
        .order_by(models.SubscriptionPlan.account_kind, models.SubscriptionPlan.sort_order)
        .all()
    )
    plan_views: list[dict] = []
    for p in plans:
        emap = {e.metric_key: e for e in (p.entitlements or [])}
        rows = [emap[k] for k in METRIC_ORDER if k in emap]
        plan_views.append({"plan": p, "rows": rows})
    default_price_hints: dict[str, str] = {}
    for (kind, code), (krw, usdc) in DEFAULT_PLAN_MONTHLY_PRICES.items():
        default_price_hints[f"{kind}:{code}"] = (
            f"미입력 시: {format_monthly_krw_display(krw)} · {format_monthly_usd_display(usdc)}"
        )
    return templates.TemplateResponse(
        request,
        "admin/subscription_plans_settings.html",
        {
            "request": request,
            "user": user,
            "settings": raw,
            "plan_views": plan_views,
            "has_plans": len(plan_views) > 0,
            "metric_labels": METRIC_LABEL_KO,
            "metric_order": METRIC_ORDER,
            "default_price_hints": default_price_hints,
        },
    )


@router.post("/subscription-plans")
async def admin_subscription_plans_settings_save(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    for key in SUBSCRIPTION_PLAN_NOTICE_KEYS:
        val = (form.get(key) or "").strip()
        existing = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
        if existing:
            existing.value = val
        else:
            db.add(models.SiteSettings(key=key, value=val))
    db.commit()
    return RedirectResponse(url="/admin/subscription-plans?saved=1", status_code=302)


@router.post("/subscription-plans/feature-descriptions")
async def admin_subscription_feature_descriptions_save(request: Request, db: Session = Depends(get_db)):
    """기능(metric)별 구독 플랜 페이지 툴팁 설명(일반 텍스트). SiteSettings subscription_metric_help_*"""
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    for mk in METRIC_ORDER:
        key = f"{SUBSCRIPTION_METRIC_HELP_KEY_PREFIX}{mk}"
        val = (form.get(key) or "").strip()
        row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
        if not val:
            if row:
                db.delete(row)
        else:
            if row:
                row.value = val
            else:
                db.add(models.SiteSettings(key=key, value=val))
    db.commit()
    return RedirectResponse(url="/admin/subscription-plans?saved_help=1", status_code=302)


@router.post("/subscription-plans/prices")
async def admin_subscription_plan_prices_save(request: Request, db: Session = Depends(get_db)):
    """플랜별 월 요금: 원화 정수·USD 달러(소수). 비우면 DB NULL → 공개 페이지 기본가."""
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    for p in db.query(models.SubscriptionPlan).all():
        krw = _parse_optional_krw_val(form.get(f"p_{p.id}_krw"))
        usd_cents = _parse_optional_usd_to_cents(form.get(f"p_{p.id}_usd"))
        p.price_monthly_krw = krw
        p.price_monthly_usd_cents = usd_cents
    db.commit()
    return RedirectResponse(url="/admin/subscription-plans?saved_prices=1", status_code=302)


_ALLOWED_PERIOD = frozenset({"monthly", "per_request", "unlimited", "disabled"})


@router.post("/subscription-plans/entitlements")
async def admin_subscription_entitlements_save(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    for ent in db.query(models.PlanEntitlement).all():
        pk = f"e_{ent.id}_period"
        lk = f"e_{ent.id}_limit"
        if pk in form:
            pt = (form.get(pk) or "").strip()
            if pt in _ALLOWED_PERIOD:
                ent.period_type = pt
        if lk in form:
            raw = (form.get(lk) or "").strip()
            if raw == "":
                ent.limit_value = None
            else:
                try:
                    ent.limit_value = int(raw)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse(url="/admin/subscription-plans?saved_ent=1", status_code=302)


@router.post("/subscription-plans/seed-catalog")
def admin_subscription_plans_seed_catalog(request: Request, db: Session = Depends(get_db)):
    """subscription_plans 테이블이 비어 있을 때만 카탈로그·entitlement 시드(운영 DB 복구용)."""
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    from ..subscription_catalog import seed_subscription_catalog

    before = db.query(models.SubscriptionPlan).count()
    seed_subscription_catalog(db)
    after = db.query(models.SubscriptionPlan).count()
    if after > before:
        return RedirectResponse(url="/admin/subscription-plans?seeded=1", status_code=302)
    return RedirectResponse(url="/admin/subscription-plans?seed_skipped=1", status_code=302)


# ── UI i18n (data-i18n 키) EN 오버라이드 ─────────────────


class AdminI18nSavePayload(BaseModel):
    key: str = Field(default="", max_length=256)
    en_text: str = Field(default="", max_length=16000)


class AdminI18nSuggestPayload(BaseModel):
    key: str = Field(default="", max_length=256)
    ko: str = Field(default="", max_length=16000)
    en_builtin: str = Field(default="", max_length=16000)
    en_override: str = Field(default="", max_length=16000)
    group_title: str = Field(default="", max_length=200)
    group_blurb: str = Field(default="", max_length=500)


@router.get("/i18n", response_class=HTMLResponse)
def admin_i18n_strings(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    groups = build_admin_grouped(db)
    return templates.TemplateResponse(
        request,
        "admin/i18n_strings.html",
        {"user": user, "groups": groups},
    )


@router.post("/i18n/save")
async def admin_i18n_save(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        payload = AdminI18nSavePayload.model_validate(await request.json())
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)
    key = (payload.key or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "empty_key"}, status_code=400)
    baseline = load_i18n_baseline()
    allowed = set((baseline.get("en") or {}).keys()) | set((baseline.get("ko") or {}).keys())
    if key not in allowed:
        return JSONResponse({"ok": False, "error": "unknown_key"}, status_code=400)
    text = (payload.en_text or "").strip()
    if not text:
        db.query(models.UiI18nEnOverride).filter(models.UiI18nEnOverride.key == key).delete()
        db.commit()
        invalidate_en_overrides_cache()
        return JSONResponse({"ok": True, "cleared": True})
    row = db.query(models.UiI18nEnOverride).filter(models.UiI18nEnOverride.key == key).first()
    if row:
        row.en_text = text
        row.updated_at = datetime.utcnow()
    else:
        db.add(models.UiI18nEnOverride(key=key, en_text=text, updated_at=datetime.utcnow()))
    db.commit()
    invalidate_en_overrides_cache()
    return JSONResponse({"ok": True})


@router.post("/i18n/ai-suggest")
async def admin_i18n_ai_suggest(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        payload = AdminI18nSuggestPayload.model_validate(await request.json())
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)
    key = (payload.key or "").strip()
    baseline = load_i18n_baseline()
    allowed = set((baseline.get("en") or {}).keys()) | set((baseline.get("ko") or {}).keys())
    if not key or key not in allowed:
        return JSONResponse({"ok": False, "error": "unknown_key"}, status_code=400)
    ko = (payload.ko or "").strip() or ((baseline.get("ko") or {}).get(key, "") or "").strip()
    if not ko:
        return JSONResponse({"ok": False, "error": "empty_korean"}, status_code=400)
    en_b = ((baseline.get("en") or {}).get(key, "") or "").strip()
    en_cur = (payload.en_builtin or en_b).strip()
    if (payload.en_override or "").strip():
        en_cur = (payload.en_override or "").strip()
    try:
        suggestion = suggest_ui_english(
            i18n_key=key,
            korean_ui=ko,
            english_current=en_cur,
            screen_title_ko=(payload.group_title or "").strip() or key,
            screen_purpose_ko=(payload.group_blurb or "").strip(),
        )
    except RuntimeError as e:
        if "GOOGLE_API_KEY" in str(e):
            return JSONResponse({"ok": False, "error": "no_api_key"}, status_code=503)
        return JSONResponse({"ok": False, "error": "model_failed"}, status_code=503)
    except ValueError:
        return JSONResponse({"ok": False, "error": "empty_korean"}, status_code=400)
    except Exception:
        return JSONResponse({"ok": False, "error": "model_failed"}, status_code=503)
    return JSONResponse({"ok": True, "text": suggestion})
