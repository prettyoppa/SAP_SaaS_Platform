from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from .database import engine, SessionLocal
from . import models
from .routers import auth_router, rfp_router, interview_router, codelib_router
from .routers import admin_router, review_router
from .templates_config import templates

# 기존 테이블 생성 (없는 테이블만 생성)
models.Base.metadata.create_all(bind=engine)


def _run_migrations():
    """신규 컬럼이 기존 DB에 없을 경우 자동으로 추가합니다 (SQLite / PostgreSQL)."""
    dialect = engine.dialect.name
    insp = inspect(engine)
    # (table, column, sqlite_def, postgres_def)
    migrations = [
        ("rfps", "interview_status", "VARCHAR DEFAULT 'pending'", "VARCHAR DEFAULT 'pending'"),
        ("rfps", "proposal_text", "TEXT", "TEXT"),
        ("rfps", "program_id", "VARCHAR", "VARCHAR"),
        ("rfps", "transaction_code", "VARCHAR", "VARCHAR"),
        ("rfps", "proposal_generated_at", "DATETIME", "TIMESTAMP"),
        ("users", "is_admin", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("rfp_messages", "source_label", "VARCHAR", "VARCHAR"),
        ("rfp_messages", "updated_at", "DATETIME", "TIMESTAMP"),
        ("abap_codes", "program_id", "VARCHAR", "VARCHAR"),
        ("abap_codes", "transaction_code", "VARCHAR", "VARCHAR"),
        ("abap_codes", "is_draft", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
    ]
    with engine.connect() as conn:
        for table, column, sqlite_def, pg_def in migrations:
            try:
                existing = [c["name"] for c in insp.get_columns(table)]
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
                db.add(models.DevType(code=code, label_ko=lbl_ko, label_en=lbl_en, sort_order=i))
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


_run_migrations()
_seed_modules_and_devtypes()
_sync_admins()

app = FastAPI(title="Catchy Lab - SAP Dev Hub", docs_url=None, redoc_url=None)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(auth_router.router)
app.include_router(rfp_router.router)
app.include_router(interview_router.router)
app.include_router(codelib_router.router)
app.include_router(admin_router.router)
app.include_router(review_router.router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    from . import auth
    from .database import SessionLocal as _SL
    _db = _SL()
    try:
        user = auth.get_current_user(request, _db)
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
    })
