import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, joinedload
from .database import SessionLocal, db_target_log_line, engine
from .email_smtp import email_verification_enabled, log_smtp_startup_checks
from .form_errors import humanize_validation_errors, request_accepts_html, safe_back_url
from . import auth, models
from .rfp_landing import DEFAULT_SERVICE_ABAP_INTRO_MD_KO
from .menu_landing import DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO, DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO
from .home_counts import home_tile_counts
from .routers import auth_router, rfp_router, interview_router, codelib_router, abap_analysis_router
from .routers import admin_router, review_router, integration_router, integration_interview_router
from .routers import payments_router, paid_admin_router
from .templates_config import templates

_log = logging.getLogger("uvicorn.error")


def _run_migrations():
    """신규 컬럼이 기존 DB에 없을 경우 자동으로 추가합니다 (SQLite / PostgreSQL)."""
    dialect = engine.dialect.name
    # (table, column, sqlite_def, postgres_def)
    migrations = [
        ("rfps", "workflow_origin", "VARCHAR DEFAULT 'direct'", "VARCHAR DEFAULT 'direct'"),
        ("rfps", "interview_status", "VARCHAR DEFAULT 'pending'", "VARCHAR DEFAULT 'pending'"),
        ("rfps", "proposal_text", "TEXT", "TEXT"),
        ("rfps", "program_id", "VARCHAR", "VARCHAR"),
        ("rfps", "transaction_code", "VARCHAR", "VARCHAR"),
        ("rfps", "proposal_generated_at", "DATETIME", "TIMESTAMP"),
        ("users", "is_admin", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "is_consultant", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "consultant_application_pending", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("rfp_messages", "source_label", "VARCHAR", "VARCHAR"),
        ("rfp_messages", "updated_at", "DATETIME", "TIMESTAMP"),
        ("abap_codes", "program_id", "VARCHAR", "VARCHAR"),
        ("abap_codes", "transaction_code", "VARCHAR", "VARCHAR"),
        ("abap_codes", "is_draft", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("rfps", "attachments_json", "TEXT", "TEXT"),
        ("rfps", "reference_code_payload", "TEXT", "TEXT"),
        ("users", "email_verified", "BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT true"),
        ("email_registration_codes", "verified_at", "DATETIME", "TIMESTAMP"),
        ("users", "phone_number", "VARCHAR(32)", "VARCHAR(32)"),
        ("users", "phone_verified", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "phone_verified_at", "DATETIME", "TIMESTAMP"),
        ("users", "ops_email_opt_in", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "ops_sms_opt_in", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "marketing_email_opt_in", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "marketing_sms_opt_in", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "consent_updated_at", "DATETIME", "TIMESTAMP"),
        ("rfp_messages", "intra_state_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "title", "VARCHAR(512) DEFAULT ''", "VARCHAR(512) DEFAULT ''"),
        ("abap_analysis_requests", "requirement_text", "TEXT DEFAULT ''", "TEXT DEFAULT ''"),
        ("abap_analysis_requests", "reference_code_payload", "TEXT", "TEXT"),
        ("abap_analysis_requests", "source_code", "TEXT DEFAULT ''", "TEXT DEFAULT ''"),
        ("abap_analysis_requests", "attachments_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "analysis_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "updated_at", "DATETIME", "TIMESTAMP"),
        ("abap_analysis_requests", "is_analyzed", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("abap_analysis_requests", "is_draft", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("integration_requests", "proposal_text", "TEXT", "TEXT"),
        ("integration_requests", "proposal_generated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "interview_status", "VARCHAR DEFAULT 'pending'", "VARCHAR DEFAULT 'pending'"),
        ("integration_requests", "reference_code_payload", "TEXT", "TEXT"),
        ("rfps", "paid_engagement_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "paid_activated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "stripe_checkout_session_id", "VARCHAR", "VARCHAR"),
        ("rfps", "fs_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "fs_text", "TEXT", "TEXT"),
        ("rfps", "fs_generated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "fs_error", "TEXT", "TEXT"),
        ("rfps", "delivered_code_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "delivered_code_text", "TEXT", "TEXT"),
        ("rfps", "delivered_code_payload", "TEXT", "TEXT"),
        ("rfps", "delivered_code_generated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "delivered_code_error", "TEXT", "TEXT"),
        ("rfps", "fs_codegen_supplement_id", "INTEGER", "INTEGER"),
        ("rfps", "fs_job_log", "TEXT", "TEXT"),
        ("rfps", "delivered_job_log", "TEXT", "TEXT"),
        ("abap_analysis_requests", "workflow_rfp_id", "INTEGER", "INTEGER"),
        ("abap_analysis_requests", "improvement_request_text", "TEXT", "TEXT"),
        ("abap_analysis_requests", "program_id", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "transaction_code", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "sap_modules", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "dev_types", "VARCHAR", "VARCHAR"),
        ("dev_types", "usage", "VARCHAR(16) DEFAULT 'abap'", "VARCHAR(16) DEFAULT 'abap'"),
        ("integration_requests", "workflow_rfp_id", "INTEGER", "INTEGER"),
        ("integration_requests", "improvement_request_text", "TEXT", "TEXT"),
        ("integration_requests", "fs_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("integration_requests", "fs_text", "TEXT", "TEXT"),
        ("integration_requests", "fs_generated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "fs_error", "TEXT", "TEXT"),
        ("integration_requests", "fs_job_log", "TEXT", "TEXT"),
        ("integration_requests", "delivered_code_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("integration_requests", "delivered_code_text", "TEXT", "TEXT"),
        ("integration_requests", "delivered_code_generated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "delivered_code_error", "TEXT", "TEXT"),
        ("integration_requests", "delivered_job_log", "TEXT", "TEXT"),
        ("users", "pending_account_deletion", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "deletion_requested_at", "DATETIME", "TIMESTAMP"),
        ("users", "deletion_hard_scheduled_at", "DATETIME", "TIMESTAMP"),
        ("users", "timezone", "VARCHAR(64)", "VARCHAR(64)"),
        ("users", "consultant_profile_file_path", "TEXT", "TEXT"),
        ("users", "consultant_profile_file_name", "VARCHAR(512)", "VARCHAR(512)"),
    ]
    with engine.connect() as conn:
        for table, column, sqlite_def, pg_def in migrations:
            try:
                existing = [c["name"] for c in inspect(engine).get_columns(table)]
            except Exception:
                continue
            if column in existing:
                continue
            col_def = pg_def if dialect == "postgresql" else sqlite_def
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                conn.commit()
            except Exception:
                conn.rollback()
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE dev_types SET usage = 'abap' "
                    "WHERE usage IS NULL OR TRIM(COALESCE(usage, '')) = ''"
                )
            )
            conn.commit()
    except Exception:
        pass


DEFAULT_INTEGRATION_IMPL_DEVTYPES = [
    ("excel_vba", "Excel / VBA 매크로", "Excel / VBA macro"),
    ("python_script", "Python 스크립트", "Python script"),
    ("small_webapp", "소규모 웹앱", "Small web app"),
    ("windows_batch", "Windows 배치 / 작업 스케줄러", "Windows batch / Task Scheduler"),
    ("api_integration", "API·시스템 연동", "API / system integration"),
    ("other", "기타", "Other"),
]
_LEGACY_INTEGRATION_CODES = {c for c, _, _ in DEFAULT_INTEGRATION_IMPL_DEVTYPES}


def _ensure_integration_impl_devtypes():
    """연동 구현 형태 기본 행(기존 하드코드 목록)을 DevType.usage=integration 으로 보장."""
    db: Session = SessionLocal()
    try:
        for i, (code, ko, en) in enumerate(DEFAULT_INTEGRATION_IMPL_DEVTYPES):
            row = db.query(models.DevType).filter(models.DevType.code == code).first()
            if row is None:
                db.add(
                    models.DevType(
                        code=code,
                        label_ko=ko,
                        label_en=en,
                        sort_order=100 + i,
                        is_active=True,
                        usage="integration",
                    )
                )
            elif (getattr(row, "usage", None) or "abap") == "abap" and code in _LEGACY_INTEGRATION_CODES:
                row.usage = "integration"
        db.commit()
    finally:
        db.close()


def _seed_home_tile_settings():
    """홈 4타일·이용가이드 PDF URL 등 기본 SiteSettings 시드."""
    defaults = [
        ("home_tile_guide_title_ko", "사용 안내"),
        ("home_tile_guide_title_en", "Getting started"),
        ("home_tile_guide_desc_ko", "PDF와 서비스 이용 방법을 확인하세요."),
        ("home_tile_guide_desc_en", "Open the PDF and learn how to use the hub."),
        ("home_tile_abap_title_ko", "신규 개발"),
        ("home_tile_abap_title_en", "New development"),
        ("home_tile_abap_desc_ko", "RFP·AI 인터뷰·제안서 기반 전형적인 ABAP 개발 요청"),
        ("home_tile_abap_desc_en", "RFP, AI interview, and proposal for classic ABAP work."),
        ("home_tile_analysis_title_ko", "분석·개선"),
        ("home_tile_analysis_title_en", "Analyze · improve"),
        ("home_tile_analysis_desc_ko", "기존 ABAP 코드 분석·진단 및 개선 방향을 제안합니다."),
        ("home_tile_analysis_desc_en", "Analyze existing ABAP, findings, and improvement suggestions."),
        ("home_tile_integration_title_ko", "연동 개발"),
        ("home_tile_integration_title_en", "Integration development"),
        ("home_tile_integration_desc_ko", "VBA, Python, API 등 비-ABAP 연동·자동화 요청"),
        ("home_tile_integration_desc_en", "Non-ABAP automation: VBA, Python, APIs, batch, small web apps."),
        ("user_guide_pdf_url", "/static/docs/user-guide.pdf"),
        ("service_abap_intro_md_ko", DEFAULT_SERVICE_ABAP_INTRO_MD_KO),
        ("service_analysis_intro_md_ko", DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO),
        ("service_integration_intro_md_ko", DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO),
    ]
    db: Session = SessionLocal()
    try:
        for key, val in defaults:
            if db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first():
                continue
            db.add(models.SiteSettings(key=key, value=val))
        db.commit()
    finally:
        db.close()


def _seed_modules_and_devtypes():
    """SAPModule, DevType 테이블이 비어있으면 기본값으로 채웁니다."""
    DEFAULT_MODULES = [
        ("SD", "SD (영업/유통)", "SD (Sales & Distribution)"),
        ("MM", "MM (구매/자재)", "MM (Materials Management)"),
        ("FI", "FI (재무회계)", "FI (Financial Accounting)"),
        ("CO", "CO (관리회계)", "CO (Controlling)"),
        ("PP", "PP (생산관리)", "PP (Production Planning)"),
        ("QM", "QM (품질관리)", "QM (Quality Management)"),
        ("PM", "PM (설비관리)", "PM (Plant Maintenance)"),
        ("HCM", "HCM (인사관리)", "HCM (Human Capital Management)"),
        ("WM", "WM (창고관리)", "WM (Warehouse Management)"),
        ("PS", "PS (프로젝트)", "PS (Project System)"),
        ("EWM", "EWM (확장창고)", "EWM (Extended Warehouse Management)"),
        ("Basis", "Basis (기술기반)", "Basis (Technical Foundation)"),
    ]
    DEFAULT_DEVTYPES = [
        ("Report_ALV",      "ALV 리포트",       "ALV Report"),
        ("Dialog",          "다이얼로그 프로그램", "Dialog Program"),
        ("Function_Module",  "Function Module",   "Function Module"),
        ("Enhancement",      "Enhancement/BAdI",  "Enhancement/BAdI"),
        ("BAPI",             "BAPI",              "BAPI"),
        ("Data_Upload",      "데이터 업로드",      "Data Upload"),
        ("Interface",        "인터페이스",         "Interface"),
        ("Form",             "SAP Form/Smart Form", "SAP Form/Smart Form"),
        ("Workflow",         "워크플로우",          "Workflow"),
        ("Fiori_Web",        "Fiori/Web",           "Fiori/Web"),
    ]

    db: Session = SessionLocal()
    try:
        if db.query(models.SAPModule).count() == 0:
            for i, (code, lbl_ko, lbl_en) in enumerate(DEFAULT_MODULES):
                db.add(models.SAPModule(code=code, label_ko=lbl_ko, label_en=lbl_en, sort_order=i))
            db.commit()

        if db.query(models.DevType).count() == 0:
            for i, (code, lbl_ko, lbl_en) in enumerate(DEFAULT_DEVTYPES):
                db.add(
                    models.DevType(
                        code=code,
                        label_ko=lbl_ko,
                        label_en=lbl_en,
                        sort_order=i,
                        usage="abap",
                    )
                )
            db.commit()
    finally:
        db.close()


def _sync_admins():
    """admins.txt 파일을 읽어 관리자 권한을 DB와 동기화합니다."""
    import os
    admins_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admins.txt")
    if not os.path.exists(admins_file):
        return

    admin_emails = set()
    with open(admins_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            admin_emails.add(line.lower())

    db = SessionLocal()
    try:
        all_users = db.query(models.User).all()
        changed = 0
        for user in all_users:
            should_be_admin = user.email.lower() in admin_emails
            if user.is_admin != should_be_admin:
                user.is_admin = should_be_admin
                changed += 1
        if changed:
            db.commit()
            print(f"[Admin Sync] {changed}명의 관리자 권한이 변경되었습니다.")
        if admin_emails:
            print(f"[Admin Sync] 관리자 이메일 {len(admin_emails)}개 로드: {', '.join(admin_emails)}")
    finally:
        db.close()


def _bootstrap_database():
    """테이블 생성·마이그레이션·시드. 실패 시 로그에 전체 traceback이 남습니다."""
    _log.info("[DB] connecting: %s", db_target_log_line())
    models.Base.metadata.create_all(bind=engine)
    _run_migrations()
    _seed_modules_and_devtypes()
    _ensure_integration_impl_devtypes()
    _seed_home_tile_settings()
    _sync_admins()
    _log.info("[DB] bootstrap complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Railway 등에서 웹 컨테이너가 Postgres보다 먼저 뜨면 첫 DB 연결이 실패할 수 있어 재시도합니다."""
    max_attempts = 8
    purge_task: asyncio.Task | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            _bootstrap_database()
            db_run = SessionLocal()
            try:
                from . import account_lifecycle

                n_del = account_lifecycle.run_scheduled_hard_deletes(db_run)
                if n_del:
                    _log.info("[Account] startup hard-delete processed %s user(s)", n_del)
            except Exception:
                _log.exception("[Account] startup purge skipped due to error")
            finally:
                db_run.close()
            break
        except Exception:
            wait = min(2 ** (attempt - 1), 30)
            if attempt >= max_attempts:
                _log.exception(
                    "[DB] Bootstrap failed after %s attempts. "
                    "확인: DATABASE_URL, DATABASE_PUBLIC_URL(app/database.py 참고).",
                    max_attempts,
                )
                raise
            _log.warning(
                "[DB] bootstrap attempt %s/%s failed — retry in %ss",
                attempt,
                max_attempts,
                wait,
            )
            await asyncio.sleep(wait)
    log_smtp_startup_checks(_log)

    async def _purge_loop():
        await asyncio.sleep(120)
        while True:
            db_loop = SessionLocal()
            try:
                from . import account_lifecycle

                account_lifecycle.run_scheduled_hard_deletes(db_loop)
            except Exception:
                _log.exception("[Account] periodic purge failed")
            finally:
                db_loop.close()
            await asyncio.sleep(3600)

    purge_task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        if purge_task:
            purge_task.cancel()
            try:
                await purge_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="SAP 개발 파트너",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz():
    """로드밸런서·Railway 헬스체크용 (DB 없이 응답)."""
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """브라우저 폼 제출(text/html) 시 422 JSON 대신 안내 화면 또는 폼 재표시."""
    errors_list = exc.errors()
    if not request_accepts_html(request):
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors_list)},
        )

    path = request.url.path
    message = humanize_validation_errors(errors_list)

    if path == "/register":
        db = SessionLocal()
        try:
            settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
            return templates.TemplateResponse(
                request,
                "register.html",
                {
                    "settings": settings,
                    "email_verification": email_verification_enabled(),
                    "error": "validation",
                    "validation_message": message,
                },
                status_code=422,
            )
        finally:
            db.close()

    if path == "/login":
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "validation",
                "validation_message": message,
            },
            status_code=422,
        )

    back = safe_back_url(request, "/")
    return templates.TemplateResponse(
        request,
        "form_validation_error.html",
        {"message": message, "back_url": back},
        status_code=422,
    )


# 서버 사이드 세션(코드 라이브러리 2차 확인 등). SESSION_SECRET 미설정 시 JWT 시크릿과 동일(운영에서는 분리 권장).
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", auth.SECRET_KEY),
    max_age=86400 * 7,
    same_site="lax",
)


@app.middleware("http")
async def no_store_html_for_logged_in_views(request: Request, call_next):
    """HTML이 Cookie별(로그인 사용자별)로 캐시되면 다른 계정 화면이 섞여 보일 수 있어 비활성화."""
    response = await call_next(request)
    ct = (response.headers.get("content-type") or "").lower()
    if "text/html" in ct:
        response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie"
    return response


_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(auth_router.router)
app.include_router(rfp_router.router)
app.include_router(interview_router.router)
app.include_router(codelib_router.router)
app.include_router(abap_analysis_router.router)
app.include_router(admin_router.router)
app.include_router(review_router.router)
app.include_router(integration_interview_router.router)
app.include_router(integration_router.router)
app.include_router(payments_router.router)
app.include_router(paid_admin_router.router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    from .database import SessionLocal as _SL
    _db = _SL()
    try:
        user = auth.get_current_user(request, _db)
        home_counts = None
        if user:
            try:
                home_counts = home_tile_counts(_db, user.id, is_admin=bool(user.is_admin))
            except Exception:
                _log.exception("home_tile_counts failed user_id=%s", getattr(user, "id", None))
                home_counts = None
        raw_settings = _db.query(models.SiteSettings).all()
        settings = {s.key: s.value for s in raw_settings}
        notices = (_db.query(models.Notice)
                   .filter(models.Notice.is_active == True)
                   .order_by(models.Notice.created_at.desc())
                   .limit(5).all())
        faqs = (_db.query(models.FAQ)
                .filter(models.FAQ.is_active == True)
                .order_by(models.FAQ.sort_order)
                .all())
        reviews = (_db.query(models.Review)
                   .options(joinedload(models.Review.author))
                   .filter(models.Review.is_public == True)
                   .order_by(models.Review.created_at.desc())
                   .limit(10).all())
    finally:
        _db.close()
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "user": user,
        "settings": settings,
        "notices": notices,
        "faqs": faqs,
        "reviews": reviews,
        "home_counts": home_counts,
    })
