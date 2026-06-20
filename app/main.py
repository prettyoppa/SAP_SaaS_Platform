import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session, joinedload
from .database import SessionLocal, db_target_log_line, engine
from .email_smtp import email_verification_enabled, log_smtp_startup_checks
from .form_errors import humanize_validation_errors, request_accepts_html, safe_back_url
from . import auth, models
from .rfp_landing import DEFAULT_SERVICE_ABAP_INTRO_MD_KO
from .menu_landing import (
    DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO,
    DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO,
    user_proposal_pending_offer_badges,
)
from .offer_inquiry_service import (
    consultant_has_any_pending_inquiry_reply,
    admin_has_any_pending_inquiry_reply,
)
from .home_counts import home_tile_counts
from .menu_landing import home_tile_stage_links
from .request_hub_access import consultant_menu_matched_scope
from .i18n_overrides import get_en_overrides_for_client
from .subscription_quota import plan_row_for_entitlements, user_subscription_plan_display_names
from .routers import auth_router, rfp_router, interview_router, codelib_router, abap_analysis_router
from .routers import admin_router, review_router, integration_router, integration_interview_router
from .routers import site_content_router, seo_router, legal_content_router
from .routers import (
    portone_router,
    preview_ia_router,
    ia_landing_router,
    project_settlement_router,
    paid_admin_router,
    proposal_supplements_router,
    proposal_decisions_router,
    billing_router,
    ai_wallet_router,
    as_built_router,
)
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
        ("users", "allow_shared_phone", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "is_test_account", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("knowledge_articles", "request_flow_key", "VARCHAR(64)", "VARCHAR(64)"),
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
        ("integration_requests", "proposal_section6_decisions_json", "TEXT", "TEXT"),
        ("integration_requests", "interview_status", "VARCHAR DEFAULT 'pending'", "VARCHAR DEFAULT 'pending'"),
        ("integration_requests", "reference_code_payload", "TEXT", "TEXT"),
        ("rfps", "proposal_section6_decisions_json", "TEXT", "TEXT"),
        ("rfps", "paid_engagement_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "paid_activated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "stripe_checkout_session_id", "VARCHAR", "VARCHAR"),
        ("rfps", "fs_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "fs_text", "TEXT", "TEXT"),
        ("rfps", "fs_consultant_addendum", "TEXT", "TEXT"),
        ("rfps", "fs_generated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "fs_error", "TEXT", "TEXT"),
        ("rfps", "delivered_code_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("rfps", "delivered_code_text", "TEXT", "TEXT"),
        ("rfps", "delivered_code_payload", "TEXT", "TEXT"),
        ("rfps", "delivered_code_generated_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "delivered_code_error", "TEXT", "TEXT"),
        ("rfps", "fs_codegen_supplement_id", "INTEGER", "INTEGER"),
        ("rfps", "fs_job_log", "TEXT", "TEXT"),
        ("rfps", "fs_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("rfps", "dev_code_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("rfps", "delivered_job_log", "TEXT", "TEXT"),
        ("abap_analysis_requests", "workflow_rfp_id", "INTEGER", "INTEGER"),
        ("abap_analysis_requests", "improvement_request_text", "TEXT", "TEXT"),
        ("abap_analysis_requests", "interview_status", "VARCHAR DEFAULT 'pending'", "VARCHAR DEFAULT 'pending'"),
        ("abap_analysis_requests", "proposal_text", "TEXT", "TEXT"),
        ("abap_analysis_requests", "proposal_generated_at", "DATETIME", "TIMESTAMP"),
        ("abap_analysis_requests", "proposal_section6_decisions_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "fs_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("abap_analysis_requests", "fs_text", "TEXT", "TEXT"),
        ("abap_analysis_requests", "fs_consultant_addendum", "TEXT", "TEXT"),
        ("abap_analysis_requests", "fs_generated_at", "DATETIME", "TIMESTAMP"),
        ("abap_analysis_requests", "fs_error", "TEXT", "TEXT"),
        ("abap_analysis_requests", "fs_job_log", "TEXT", "TEXT"),
        ("abap_analysis_requests", "fs_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("abap_analysis_requests", "dev_code_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("abap_analysis_requests", "delivered_code_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("abap_analysis_requests", "delivered_code_text", "TEXT", "TEXT"),
        ("abap_analysis_requests", "delivered_code_payload", "TEXT", "TEXT"),
        ("abap_analysis_requests", "delivered_code_generated_at", "DATETIME", "TIMESTAMP"),
        ("abap_analysis_requests", "delivered_code_error", "TEXT", "TEXT"),
        ("abap_analysis_requests", "delivered_job_log", "TEXT", "TEXT"),
        ("abap_analysis_requests", "paid_engagement_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("abap_analysis_requests", "paid_activated_at", "DATETIME", "TIMESTAMP"),
        ("abap_analysis_requests", "program_id", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "transaction_code", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "sap_modules", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "dev_types", "VARCHAR", "VARCHAR"),
        ("abap_analysis_requests", "requirement_screenshots_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "requirement_text_format", "VARCHAR(16) DEFAULT 'plain'", "VARCHAR(16) DEFAULT 'plain'"),
        ("rfps", "description_format", "VARCHAR(16) DEFAULT 'plain'", "VARCHAR(16) DEFAULT 'plain'"),
        ("rfps", "requirement_screenshots_json", "TEXT", "TEXT"),
        ("dev_types", "usage", "VARCHAR(16) DEFAULT 'abap'", "VARCHAR(16) DEFAULT 'abap'"),
        ("integration_requests", "description_format", "VARCHAR(16) DEFAULT 'plain'", "VARCHAR(16) DEFAULT 'plain'"),
        ("integration_requests", "requirement_screenshots_json", "TEXT", "TEXT"),
        ("integration_requests", "workflow_rfp_id", "INTEGER", "INTEGER"),
        ("integration_requests", "improvement_request_text", "TEXT", "TEXT"),
        ("integration_requests", "paid_engagement_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("integration_requests", "paid_activated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "fs_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("integration_requests", "fs_text", "TEXT", "TEXT"),
        ("integration_requests", "fs_consultant_addendum", "TEXT", "TEXT"),
        ("integration_requests", "fs_generated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "fs_error", "TEXT", "TEXT"),
        ("integration_requests", "fs_job_log", "TEXT", "TEXT"),
        ("integration_requests", "fs_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("integration_requests", "dev_code_visible_to_requester", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("integration_requests", "delivered_code_status", "VARCHAR DEFAULT 'none'", "VARCHAR DEFAULT 'none'"),
        ("integration_requests", "delivered_code_text", "TEXT", "TEXT"),
        ("integration_requests", "delivered_code_payload", "TEXT", "TEXT"),
        ("integration_requests", "delivered_code_generated_at", "DATETIME", "TIMESTAMP"),
        ("integration_requests", "delivered_code_error", "TEXT", "TEXT"),
        ("integration_requests", "delivered_job_log", "TEXT", "TEXT"),
        ("users", "pending_account_deletion", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("users", "deletion_requested_at", "DATETIME", "TIMESTAMP"),
        ("users", "deletion_hard_scheduled_at", "DATETIME", "TIMESTAMP"),
        ("users", "timezone", "VARCHAR(64)", "VARCHAR(64)"),
        ("users", "consultant_profile_file_path", "TEXT", "TEXT"),
        ("users", "consultant_profile_file_name", "VARCHAR(512)", "VARCHAR(512)"),
        ("request_offer_inquiries", "parent_inquiry_id", "INTEGER", "INTEGER"),
        ("rfp_followup_messages", "thread_user_id", "INTEGER", "INTEGER"),
        ("integration_followup_messages", "thread_user_id", "INTEGER", "INTEGER"),
        ("abap_analysis_followup_messages", "thread_user_id", "INTEGER", "INTEGER"),
        ("request_offers", "match_notice_pending", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("notices", "sort_order", "INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
        ("reviews", "admin_suppressed", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("reviews", "display_name", "VARCHAR(200)", "VARCHAR(200)"),
        ("users", "subscription_plan_code", "VARCHAR(32) DEFAULT 'experience'", "VARCHAR(32) DEFAULT 'experience'"),
        ("users", "subscription_plan_source", "VARCHAR(20) DEFAULT 'default'", "VARCHAR(20) DEFAULT 'default'"),
        ("users", "subscription_plan_expires_at", "DATETIME", "TIMESTAMP"),
        ("users", "experience_trial_ends_at", "DATETIME", "TIMESTAMP"),
        ("users", "billing_country", "VARCHAR(2)", "VARCHAR(2)"),
        ("users", "preferred_lang", "VARCHAR(2) DEFAULT 'ko'", "VARCHAR(2) DEFAULT 'ko'"),
        ("users", "billing_currency", "VARCHAR(3) DEFAULT 'KRW'", "VARCHAR(3) DEFAULT 'KRW'"),
        ("users", "ai_wallet_balance_krw", "INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
        ("payment_claims", "wallet_credited_on_submit", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("payment_claims", "confirmed_amount_minor", "INTEGER", "INTEGER"),
        ("payment_claims", "project_settlement_id", "INTEGER", "INTEGER"),
        ("project_settlements", "payment_method", "VARCHAR(20)", "VARCHAR(20)"),
        ("project_settlements", "portone_payment_id", "VARCHAR(128)", "VARCHAR(128)"),
        ("subscription_plans", "price_monthly_krw", "INTEGER", "INTEGER"),
        ("subscription_plans", "price_monthly_usd_cents", "INTEGER", "INTEGER"),
        ("notices", "title_en", "TEXT", "TEXT"),
        ("notices", "content_en", "TEXT", "TEXT"),
        ("notices", "updated_at", "DATETIME", "TIMESTAMP"),
        ("notices", "show_home_popup", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("faqs", "question_en", "TEXT", "TEXT"),
        ("faqs", "answer_en", "TEXT", "TEXT"),
        ("rfp_fs_supplements", "request_kind", "VARCHAR(32) DEFAULT 'rfp'", "VARCHAR(32) DEFAULT 'rfp'"),
        ("rfp_fs_supplements", "request_id", "INTEGER", "INTEGER"),
        ("knowledge_articles", "workflow_status", "VARCHAR(32) DEFAULT 'draft'", "VARCHAR(32) DEFAULT 'draft'"),
        ("knowledge_articles", "reviewed_at", "DATETIME", "TIMESTAMP"),
        ("knowledge_articles", "seed_keyword", "VARCHAR(200)", "VARCHAR(200)"),
        ("knowledge_articles", "research_summary", "TEXT", "TEXT"),
        ("knowledge_articles", "body_format", "VARCHAR(16) DEFAULT 'markdown'", "VARCHAR(16) DEFAULT 'markdown'"),
        ("knowledge_articles", "body_screenshots_json", "TEXT", "TEXT"),
        ("knowledge_articles", "body_format_en", "VARCHAR(16)", "VARCHAR(16)"),
        ("knowledge_articles", "author_user_id", "INTEGER", "INTEGER"),
        ("kb_gallery_batch_jobs", "source_mode", "VARCHAR(16) DEFAULT 'keywords'", "VARCHAR(16) DEFAULT 'keywords'"),
        ("kb_gallery_batch_jobs", "also_english", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false"),
        ("kb_gallery_batch_jobs", "keynote_text", "TEXT", "TEXT"),
        ("kb_gallery_batch_jobs", "cancel_requested_at", "DATETIME", "TIMESTAMP"),
        ("rfps", "as_built_zip_json", "TEXT", "TEXT"),
        ("integration_requests", "as_built_zip_json", "TEXT", "TEXT"),
        ("abap_analysis_requests", "as_built_zip_json", "TEXT", "TEXT"),
        ("rfps", "sap_system_version", "VARCHAR(32)", "VARCHAR(32)"),
        ("rfps", "sap_system_version_note", "VARCHAR(120)", "VARCHAR(120)"),
        ("abap_analysis_requests", "sap_system_version", "VARCHAR(32)", "VARCHAR(32)"),
        ("abap_analysis_requests", "sap_system_version_note", "VARCHAR(120)", "VARCHAR(120)"),
        ("rfps", "delivered_code_working_payload", "TEXT", "TEXT"),
        ("integration_requests", "delivered_code_working_payload", "TEXT", "TEXT"),
        ("abap_analysis_requests", "delivered_code_working_payload", "TEXT", "TEXT"),
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
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE rfp_fs_supplements SET request_id = rfp_id, request_kind = 'rfp' "
                    "WHERE request_id IS NULL AND rfp_id IS NOT NULL"
                )
            )
            conn.commit()
    except Exception:
        pass
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE rfp_followup_messages SET thread_user_id = "
                    "(SELECT user_id FROM rfps WHERE rfps.id = rfp_followup_messages.rfp_id) "
                    "WHERE thread_user_id IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE integration_followup_messages SET thread_user_id = "
                    "(SELECT user_id FROM integration_requests WHERE integration_requests.id = "
                    "integration_followup_messages.request_id) "
                    "WHERE thread_user_id IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE abap_analysis_followup_messages SET thread_user_id = "
                    "(SELECT user_id FROM abap_analysis_requests WHERE abap_analysis_requests.id = "
                    "abap_analysis_followup_messages.request_id) "
                    "WHERE thread_user_id IS NULL"
                )
            )
            conn.commit()
    except Exception:
        pass
    try:
        models.ReviewRating.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        models.AccountPhoneOtp.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        models.AgentPlaybookEntry.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        models.PaymentClaim.__table__.create(bind=engine, checkfirst=True)
        models.AiUsageEvent.__table__.create(bind=engine, checkfirst=True)
        models.PlatformAuditEvent.__table__.create(bind=engine, checkfirst=True)
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


def _seed_legal_site_content():
    """docs/legal·user_guide 초안 → SiteSettings (비어 있거나 파일 해시 변경 시)."""
    from .content_drafts import sync_content_drafts_from_files

    db = SessionLocal()
    try:
        if sync_content_drafts_from_files(db, force=False):
            _log.info("[DB] content drafts synced from docs/ to SiteSettings")
    except Exception:
        _log.exception("[DB] content drafts sync failed")
        db.rollback()
    finally:
        db.close()


def _migrate_nav_aligned_labels():
    """홈 타일 EN·i18n EN 오버라이드가 구형 장문/오역이면 네비 짧은 라벨로 맞춤."""
    from .ui_nav_labels import migrate_home_tile_en_nav_labels, migrate_i18n_en_nav_overrides

    db = SessionLocal()
    try:
        n1 = migrate_home_tile_en_nav_labels(db)
        n2 = migrate_i18n_en_nav_overrides(db)
        if n1 or n2:
            from .i18n_overrides import invalidate_en_overrides_cache

            invalidate_en_overrides_cache()
            _log.info("[DB] nav-aligned labels migrated (tiles=%s, i18n=%s)", n1, n2)
    except Exception:
        _log.exception("[DB] nav-aligned label migration failed")
        db.rollback()
    finally:
        db.close()


def _seed_home_tile_settings():
    """홈 4타일·이용가이드 PDF URL 등 기본 SiteSettings 시드."""
    defaults = [
        ("home_tile_guide_title_ko", "사용 안내"),
        ("home_tile_guide_title_en", "Getting started"),
        ("home_guide_video_url", ""),
        ("home_guide_text_md", ""),
        ("home_guide_text_md_en", ""),
        ("home_tile_abap_title_ko", "신규 개발"),
        ("home_tile_abap_title_en", "Develop"),
        ("home_tile_abap_desc_ko", "RFP·AI 인터뷰·제안서 기반 전형적인 ABAP 개발 요청"),
        ("home_tile_abap_desc_en", "RFP, AI interview, and proposal for classic ABAP work."),
        ("home_tile_analysis_title_ko", "분석·개선"),
        ("home_tile_analysis_title_en", "Improve"),
        ("home_tile_analysis_desc_ko", "기존 ABAP 코드 분석·진단 및 개선 방향을 제안합니다."),
        ("home_tile_analysis_desc_en", "Analyze existing ABAP, findings, and improvement suggestions."),
        ("home_tile_integration_title_ko", "연동 개발"),
        ("home_tile_integration_title_en", "Connect"),
        ("home_tile_integration_desc_ko", "VBA, Python, API 등 비-ABAP 연동·자동화 요청"),
        ("home_tile_integration_desc_en", "Non-ABAP automation: VBA, Python, APIs, batch, small web apps."),
        ("user_guide_pdf_url", "/static/docs/user-guide.pdf"),
        ("subscription_plans_notice_md_ko", ""),
        ("subscription_plans_notice_md_en", ""),
        ("bank_transfer_notice_md_ko", ""),
        ("bank_transfer_notice_md_en", ""),
        ("bank_transfer_notice_usd_md_ko", ""),
        ("bank_transfer_notice_usd_md_en", ""),
        (
            "bank_transfer_activation_sla_ko",
            "충전 신청 즉시 잔액에 반영되어 바로 AI를 이용할 수 있습니다. 입금이 확인되지 않으면 관리자가 잔액을 조정할 수 있습니다.",
        ),
        (
            "bank_transfer_activation_sla_en",
            "Your balance updates immediately when you submit a top-up, so you can use AI right away. "
            "If the transfer is not verified, an admin may adjust your balance.",
        ),
        ("usd_krw_rate", "1350"),
        ("ai_usage_markup_percent", "30"),
        ("ai_wallet_min_topup_krw", "30000"),
        ("experience_trial_days", "14"),
        ("service_abap_intro_md_ko", DEFAULT_SERVICE_ABAP_INTRO_MD_KO),
        ("service_analysis_intro_md_ko", DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO),
        ("service_integration_intro_md_ko", DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO),
        ("audit_digest_email_enabled", "1"),
        ("audit_digest_sms_enabled", "0"),
        ("audit_digest_last_sent_at", ""),
        ("audit_digest_last_event_id", "0"),
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


def _seed_subscription_catalog():
    """구독 플랜·entitlement 초기 데이터(테이블 비어 있을 때만)."""
    db: Session = SessionLocal()
    try:
        from .subscription_catalog import backfill_subscription_plan_prices_if_null, seed_subscription_catalog

        seed_subscription_catalog(db)
        backfill_subscription_plan_prices_if_null(db)
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


def _backfill_payment_claim_confirmed_amounts():
    """확인 완료 건: 확인 금액이 비어 있으면 신청 금액으로 채움."""
    db = SessionLocal()
    try:
        rows = (
            db.query(models.PaymentClaim)
            .filter(
                models.PaymentClaim.status == "confirmed",
                models.PaymentClaim.confirmed_amount_minor.is_(None),
            )
            .all()
        )
        for row in rows:
            row.confirmed_amount_minor = int(row.amount_minor)
        if rows:
            db.commit()
    finally:
        db.close()


def _migrate_wallet_deduct_historical_ai_usage():
    """기존 AI 사용 추정 비용을 지갑에 1회 반영(이후 호출분은 log_ai_usage_event에서 차감)."""
    from .ai_usage_recorder import aggregate_usage_for_user
    from .ai_wallet import apply_wallet_debit, krw_from_usage_usd_micro, usd_krw_rate_from_db

    flag_key = "ai_wallet_usage_deduct_v1"
    db: Session = SessionLocal()
    try:
        flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == flag_key).first()
        if flag and (flag.value or "").strip() == "1":
            return
        rate = usd_krw_rate_from_db(db)
        for user in db.query(models.User).all():
            agg = aggregate_usage_for_user(db, user.id)
            micro = int(agg.get("total_usd_micro") or 0)
            if micro <= 0:
                continue
            krw = krw_from_usage_usd_micro(micro, rate)
            if krw > 0:
                apply_wallet_debit(user, krw)
        if not flag:
            db.add(models.SiteSettings(key=flag_key, value="1"))
        else:
            flag.value = "1"
        db.commit()
    finally:
        db.close()


def _clamp_member_negative_ai_wallets():
    """일반·컨설턴트 계정 음수 AI 잔액을 0으로 보정(관리자 제외, 1회)."""
    from . import models

    flag_key = "ai_wallet_member_nonneg_v1"
    db = SessionLocal()
    try:
        flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == flag_key).first()
        if flag and (flag.value or "").strip() == "1":
            return
        rows = (
            db.query(models.User)
            .filter(models.User.is_admin.is_(False))
            .all()
        )
        changed = 0
        for user in rows:
            bal = int(getattr(user, "ai_wallet_balance_krw", None) or 0)
            if bal < 0:
                user.ai_wallet_balance_krw = 0
                changed += 1
        if not flag:
            db.add(models.SiteSettings(key=flag_key, value="1"))
        else:
            flag.value = "1"
        db.commit()
        if changed:
            import logging

            logging.getLogger(__name__).info(
                "Clamped negative ai_wallet_balance_krw for %s non-admin user(s)", changed
            )
    finally:
        db.close()


def _migrate_bank_transfer_sla_for_wallet():
    """구독 플랜 시절 기본 SLA 문구 → AI 잔액 즉시 반영 안내."""
    legacy = {
        "bank_transfer_activation_sla_ko": "영업일 1~2일 내 플랜을 활성화합니다.",
        "bank_transfer_activation_sla_en": "We activate your plan within 1–2 business days.",
    }
    updated = {
        "bank_transfer_activation_sla_ko": (
            "충전 신청 즉시 잔액에 반영되어 바로 AI를 이용할 수 있습니다. "
            "입금이 확인되지 않으면 관리자가 잔액을 조정할 수 있습니다."
        ),
        "bank_transfer_activation_sla_en": (
            "Your balance updates immediately when you submit a top-up, so you can use AI right away. "
            "If the transfer is not verified, an admin may adjust your balance."
        ),
    }
    db = SessionLocal()
    try:
        for key, old in legacy.items():
            row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
            if row and (row.value or "").strip() == old:
                row.value = updated[key]
        db.commit()
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
    _migrate_nav_aligned_labels()
    _seed_subscription_catalog()
    _seed_legal_site_content()
    _migrate_bank_transfer_sla_for_wallet()
    _backfill_payment_claim_confirmed_amounts()
    _migrate_wallet_deduct_historical_ai_usage()
    _clamp_member_negative_ai_wallets()
    _migrate_kb_workflow_statuses()
    _bootstrap_abap_api_kb()
    _sync_admins()
    _log.info("[DB] bootstrap complete")


def _bootstrap_abap_api_kb():
    from .abap_api_kb import bootstrap_lint_kb_entries

    db = SessionLocal()
    try:
        n = bootstrap_lint_kb_entries(db)
        if n:
            _log.info("[AbapApiKb] bootstrapped %s lint pattern(s)", n)
    except Exception:
        _log.exception("[AbapApiKb] lint bootstrap skipped")
    finally:
        db.close()


def _migrate_kb_workflow_statuses():
    from .kb_workflow import migrate_legacy_workflow_statuses

    db = SessionLocal()
    try:
        migrate_legacy_workflow_statuses(db)
    except Exception:
        _log.exception("[DB] kb workflow_status backfill skipped")
    finally:
        db.close()


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
    try:
        from .proposal_export import ensure_proposal_pdf_fonts

        ensure_proposal_pdf_fonts()
    except Exception:
        _log.exception("[PDF] startup font ensure skipped due to error")

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

    async def _audit_digest_loop():
        await asyncio.sleep(180)
        while True:
            db_loop = SessionLocal()
            try:
                from .platform_audit_digest import run_audit_digest

                n = run_audit_digest(db_loop)
                if n:
                    _log.info("[Audit] digest sent for %s event(s)", n)
            except Exception:
                _log.exception("[Audit] periodic digest failed")
            finally:
                db_loop.close()
            await asyncio.sleep(3600)

    purge_task = asyncio.create_task(_purge_loop())
    audit_digest_task = asyncio.create_task(_audit_digest_loop())
    try:
        yield
    finally:
        if purge_task:
            purge_task.cancel()
            try:
                await purge_task
            except asyncio.CancelledError:
                pass
        if audit_digest_task:
            audit_digest_task.cancel()
            try:
                await audit_digest_task
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


def _dev_theme_preview_enabled() -> bool:
    v = (os.environ.get("SAP_DEV_THEME_PREVIEW") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


@app.get("/dev/theme-preview", response_class=HTMLResponse)
def dev_theme_preview_page(request: Request):
    """라이트 테마 제안 팔레트 미리보기. 로컬에서 SAP_DEV_THEME_PREVIEW=1 일 때만."""
    if not _dev_theme_preview_enabled():
        return HTMLResponse(
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>404</title></head>"
            "<body><p>Not found.</p></body></html>",
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "dev/theme_preview.html",
        {"request": request},
    )


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

    if path == "/rfp/new" or (
        path.startswith("/rfp/") and path.endswith("/edit")
    ):
        db = SessionLocal()
        try:
            from .routers.rfp_router import rfp_form_request_validation_response

            rfp_resp = await rfp_form_request_validation_response(request, db)
            if rfp_resp is not None:
                return rfp_resp
        finally:
            db.close()

    if path == "/abap-analysis/new" or (
        path.startswith("/abap-analysis/") and path.endswith("/edit")
    ):
        db = SessionLocal()
        try:
            from .routers.abap_analysis_router import abap_form_request_validation_response

            abap_resp = await abap_form_request_validation_response(request, db)
            if abap_resp is not None:
                return abap_resp
        finally:
            db.close()

    if path == "/integration/new" or (
        path.startswith("/integration/") and path.endswith("/edit")
    ):
        db = SessionLocal()
        try:
            from .routers.integration_router import integration_form_request_validation_response

            int_resp = await integration_form_request_validation_response(request, db)
            if int_resp is not None:
                return int_resp
        finally:
            db.close()

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
async def search_referral_alert_middleware(request: Request, call_next):
    """검색엔진 Referer 유입 시 관리자 SMS(직접·자사·봇·관리자 세션 제외)."""
    try:
        from .search_referral_alert import schedule_search_referral_check

        schedule_search_referral_check(request)
    except Exception:
        _log.exception("search_referral_alert_middleware failed")
    return await call_next(request)


@app.middleware("http")
async def nav_proposal_offer_badges_middleware(request: Request, call_next):
    """상단 메뉴(신규·분석·연동) 오퍼 알림 점용 — 제안 버킷에 미매칭 오퍼가 있으면 True."""
    badges = {"rfp": False, "analysis": False, "integration": False}
    nav_console_pending_inquiry = False
    request.state.subscription_plan_display_ko = None
    request.state.subscription_plan_display_en = None
    u = getattr(request.state, "current_user", None)
    if u:
        db = SessionLocal()
        try:
            badges = user_proposal_pending_offer_badges(db, u.id)
            if getattr(u, "is_admin", False):
                nav_console_pending_inquiry = admin_has_any_pending_inquiry_reply(db)
            elif getattr(u, "is_consultant", False):
                nav_console_pending_inquiry = consultant_has_any_pending_inquiry_reply(db, u.id)
            sp_ko, sp_en = user_subscription_plan_display_names(db, u)
            request.state.subscription_plan_display_ko = sp_ko
            request.state.subscription_plan_display_en = sp_en
        finally:
            db.close()
    request.state.nav_proposal_offer_badges = badges
    request.state.nav_console_pending_inquiry = nav_console_pending_inquiry
    return await call_next(request)


@app.middleware("http")
async def i18n_en_overrides_middleware(request: Request, call_next):
    """data-i18n EN 문구 오버라이드(관리자 저장) — base.html에서 window.__I18nEnOverrides 로 전달."""
    try:
        request.state.i18n_en_overrides = get_en_overrides_for_client()
    except Exception:
        _log.exception("i18n_en_overrides_middleware failed")
        request.state.i18n_en_overrides = {}
    return await call_next(request)


@app.middleware("http")
async def language_hint_middleware(request: Request, call_next):
    """초기 언어 힌트: 로그인 회원 선호언어 > 국가(비-KR→en) > Accept-Language 1순위."""
    from .i18n_hint import initial_lang_from_request

    preferred = ""
    u = getattr(request.state, "current_user", None)
    if u and (getattr(u, "preferred_lang", "") or "").strip().lower() in ("ko", "en"):
        preferred = (u.preferred_lang or "").strip().lower()
    if not preferred:
        preferred = initial_lang_from_request(request)
    request.state.initial_lang = preferred
    request.state.lang_guest_hint = not getattr(request.state, "is_logged_in", False)
    return await call_next(request)


@app.middleware("http")
async def static_vendor_cache_middleware(request: Request, call_next):
    """vendor CSS/woff2 — 장기 캐시(아이콘·Bootstrap 재다운로드 방지)."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/vendor/") or path == "/static/css/fa-font-display-swap.css":
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


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


@app.middleware("http")
async def current_user_middleware(request: Request, call_next):
    from .request_middleware import current_user_middleware as _load_user

    return await _load_user(request, call_next)


_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_GSC_VERIFY_HTML = (
    Path(__file__).resolve().parent / "google_site_verification" / "google693a7398e24fb256.html"
)


@app.get("/google693a7398e24fb256.html")
def google_search_console_verify():
    """Google Search Console URL-prefix ownership (HTML file)."""
    return FileResponse(_GSC_VERIFY_HTML, media_type="text/html")


app.include_router(seo_router.router)
app.include_router(auth_router.router)
app.include_router(rfp_router.router)
app.include_router(interview_router.router)
app.include_router(codelib_router.router)
app.include_router(abap_analysis_router.router)
app.include_router(admin_router.router)
app.include_router(review_router.router)
app.include_router(site_content_router.router)
app.include_router(legal_content_router.router)
app.include_router(integration_interview_router.router)
app.include_router(integration_router.router)
app.include_router(portone_router.router)
app.include_router(project_settlement_router.router)
app.include_router(paid_admin_router.router)
app.include_router(proposal_supplements_router.router)
app.include_router(proposal_decisions_router.router)
app.include_router(billing_router.router)
app.include_router(ai_wallet_router.router)
app.include_router(as_built_router.router)
app.include_router(preview_ia_router.router)
app.include_router(ia_landing_router.router)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    from .database import SessionLocal as _SL
    from .site_settings_locale import enrich_site_settings, load_home_settings_dict

    user = getattr(request.state, "current_user", None)
    if not user:
        _db = _SL()
        try:
            from .guest_landing import render_guest_landing

            oauth_error = (request.query_params.get("oauth_error") or "").strip()
            return render_guest_landing(request, _db, oauth_error=oauth_error)
        finally:
            _db.close()

    _db = _SL()
    reviews: list = []
    service_intro_ctx: dict[str, str] = {}
    try:
        home_counts = None
        home_tile_stage_links_ctx: dict[str, dict[str, str]] | None = None
        try:
            home_counts = home_tile_counts(
                _db,
                user.id,
                is_admin=bool(user.is_admin),
                consultant_matched=consultant_menu_matched_scope(user),
            )
            home_tile_stage_links_ctx = {
                "rfp": home_tile_stage_links("rfp"),
                "analysis": home_tile_stage_links("analysis"),
                "integration": home_tile_stage_links("integration"),
            }
        except Exception:
            _log.exception("home_tile_counts failed user_id=%s", getattr(user, "id", None))
            home_counts = None
            home_tile_stage_links_ctx = None
        settings = enrich_site_settings(_db, load_home_settings_dict(_db), scope="home")
        from .service_landing_intro import service_landing_intro_context

        service_intro_ctx = service_landing_intro_context(_db)
        notices = (
            _db.query(models.Notice)
            .filter(models.Notice.is_active == True)
            .order_by(models.Notice.sort_order.asc(), models.Notice.created_at.asc())
            .limit(5)
            .all()
        )
        from .notice_popup import get_home_popup_notices

        home_popup_notices = get_home_popup_notices(_db)
        faqs = (
            _db.query(models.FAQ)
            .filter(models.FAQ.is_active == True)
            .order_by(models.FAQ.sort_order.asc(), models.FAQ.created_at.asc())
            .limit(5)
            .all()
        )
        _rcc = (
            _db.query(models.ReviewComment.review_id, func.count(models.ReviewComment.id).label("n"))
            .group_by(models.ReviewComment.review_id)
            .subquery()
        )
        _ravg = (
            _db.query(
                models.ReviewRating.review_id,
                func.avg(models.ReviewRating.stars).label("avg_s"),
            )
            .group_by(models.ReviewRating.review_id)
            .subquery()
        )
        reviews = (
            _db.query(models.Review)
            .options(joinedload(models.Review.author))
            .outerjoin(_rcc, models.Review.id == _rcc.c.review_id)
            .outerjoin(_ravg, models.Review.id == _ravg.c.review_id)
            .filter(models.Review.is_public == True, models.Review.admin_suppressed == False)
            .order_by(
                func.coalesce(_rcc.c.n, 0).desc(),
                func.coalesce(_ravg.c.avg_s, 0).desc(),
                models.Review.created_at.desc(),
            )
            .limit(10)
            .all()
        )
    finally:
        _db.close()
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "user": user,
        "settings": settings,
        "notices": notices,
        "home_popup_notices": home_popup_notices,
        "faqs": faqs,
        "reviews": reviews,
        "home_counts": home_counts,
        "home_tile_stage_links": home_tile_stage_links_ctx,
        **service_intro_ctx,
    })


@app.get("/subscription-plans", response_class=HTMLResponse)
def subscription_plans_page(request: Request):
    """레거시 URL → AI 잔액·사용량 페이지."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/account/ai-credits", status_code=302)


@app.get("/subscription-plans-legacy", response_class=HTMLResponse)
def subscription_plans_legacy_page(request: Request):
    """구독 플랜 비교(Admin 미리보기용; 공개 메뉴에서는 사용 안 함)."""
    from .database import SessionLocal as _SL
    from .subscription_catalog import (
        CONSULTANT_PLAN_PUBLIC_ORDER,
        MEMBER_PLAN_PUBLIC_ORDER,
        METRIC_ORDER,
        METRIC_LABEL_EN,
        METRIC_LABEL_KO,
        SUBSCRIPTION_METRIC_HELP_KEY_PREFIX,
        format_monthly_krw_display,
        format_monthly_usd_display,
        resolve_plan_monthly_prices,
    )

    _db = _SL()
    raw_settings: dict = {}
    user = None
    plan_prices_member: dict[str, dict[str, str]] = {}
    plan_prices_consultant: dict[str, dict[str, str]] = {}
    subscription_current_plan_kind: str | None = None
    subscription_current_plan_code: str | None = None
    try:
        user = auth.get_current_user(request, _db)
        raw_settings = {s.key: s.value for s in _db.query(models.SiteSettings).all()}
        from .site_settings_locale import enrich_site_settings

        raw_settings = enrich_site_settings(_db, raw_settings, scope="billing")
        active_plans = (
            _db.query(models.SubscriptionPlan)
            .filter(models.SubscriptionPlan.is_active.is_(True))
            .all()
        )
        by_key = {(p.account_kind, p.code): p for p in active_plans}
        for code in MEMBER_PLAN_PUBLIC_ORDER:
            p = by_key.get(("member", code))
            if not p:
                continue
            krw, usdc = resolve_plan_monthly_prices(p)
            plan_prices_member[code] = {
                "fmt_krw": format_monthly_krw_display(krw),
                "fmt_usd": format_monthly_usd_display(usdc),
                "show_period": not (krw == 0 and usdc == 0),
            }
        for code in CONSULTANT_PLAN_PUBLIC_ORDER:
            p = by_key.get(("consultant", code))
            if not p:
                continue
            krw, usdc = resolve_plan_monthly_prices(p)
            plan_prices_consultant[code] = {
                "fmt_krw": format_monthly_krw_display(krw),
                "fmt_usd": format_monthly_usd_display(usdc),
                "show_period": not (krw == 0 and usdc == 0),
            }
        if user and not getattr(user, "is_admin", False):
            prow = plan_row_for_entitlements(_db, user)
            if prow:
                subscription_current_plan_kind = prow.account_kind
                subscription_current_plan_code = prow.code
    finally:
        _db.close()
    metric_help: dict[str, str] = {}
    for mk in METRIC_ORDER:
        k = f"{SUBSCRIPTION_METRIC_HELP_KEY_PREFIX}{mk}"
        v = (raw_settings.get(k) or "").strip()
        if v:
            metric_help[mk] = v
    return templates.TemplateResponse(
        request,
        "subscription_plans.html",
        {
            "request": request,
            "user": user,
            "subscription_notice_md_ko": (raw_settings.get("subscription_plans_notice_md_ko") or "").strip(),
            "subscription_notice_md_en": (raw_settings.get("subscription_plans_notice_md_en") or "").strip(),
            "bank_transfer_notice_md_ko": (raw_settings.get("bank_transfer_notice_md_ko") or "").strip(),
            "bank_transfer_notice_md_en": (raw_settings.get("bank_transfer_notice_md_en") or "").strip(),
            "bank_transfer_notice_usd_md_ko": (raw_settings.get("bank_transfer_notice_usd_md_ko") or "").strip(),
            "bank_transfer_notice_usd_md_en": (raw_settings.get("bank_transfer_notice_usd_md_en") or "").strip(),
            "bank_transfer_sla_ko": (raw_settings.get("bank_transfer_activation_sla_ko") or "").strip(),
            "bank_transfer_sla_en": (raw_settings.get("bank_transfer_activation_sla_en") or "").strip(),
            "metric_labels": METRIC_LABEL_KO,
            "metric_labels_en": METRIC_LABEL_EN,
            "metric_help": metric_help,
            "plan_prices_member": plan_prices_member,
            "plan_prices_consultant": plan_prices_consultant,
            "subscription_current_plan_kind": subscription_current_plan_kind,
            "subscription_current_plan_code": subscription_current_plan_code,
        },
    )
