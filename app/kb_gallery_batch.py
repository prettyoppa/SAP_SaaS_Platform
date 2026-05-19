"""지식갤러리 — 키워드 일괄 초안 생성 백그라운드 작업."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from . import models
from .ai_usage_recorder import AiUsageContext, ai_usage_scope, log_ai_usage_event
from .database import SessionLocal
from .kb_article_generator import generate_kb_draft_from_keyword, parse_keyword_lines
from .kb_slug import ensure_unique_kb_slug, slugify_kb_title
from .kb_workflow import STATUS_PENDING_REVIEW
from .routers.site_content_router import KB_CATEGORIES

_log = logging.getLogger(__name__)

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def _append_error(job: models.KbGalleryBatchJob, line: str) -> None:
    cur = (job.errors_text or "").strip()
    job.errors_text = (cur + "\n" + line).strip()[:8000]


def run_kb_gallery_batch_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(models.KbGalleryBatchJob).filter(models.KbGalleryBatchJob.id == job_id).first()
        if not job:
            return
        try:
            keywords = json.loads(job.keywords_json or "[]")
        except Exception:
            keywords = []
        if not isinstance(keywords, list):
            keywords = []
        ref_notes = (job.reference_notes or "").strip()
        cat = (job.category_default or "general").strip().lower()
        if cat not in KB_CATEGORIES:
            cat = "general"

        job.status = STATUS_RUNNING
        job.updated_at = datetime.utcnow()
        db.commit()

        with ai_usage_scope(
            AiUsageContext(user_id=job.admin_user_id, request_kind="kb_gallery")
        ):
            for kw in keywords:
                kw_s = str(kw).strip()
                if not kw_s:
                    continue
                job.current_keyword = kw_s[:200]
                job.updated_at = datetime.utcnow()
                db.commit()
                try:
                    payload = generate_kb_draft_from_keyword(
                        keyword=kw_s,
                        reference_notes=ref_notes,
                        category_hint=cat,
                    )
                    title = payload["title"]
                    base_slug = slugify_kb_title(title) or slugify_kb_title(kw_s)
                    final_slug = ensure_unique_kb_slug(db, base_slug)
                    art_cat = payload.get("category") or cat
                    if art_cat not in KB_CATEGORIES:
                        art_cat = cat
                    db.add(
                        models.KnowledgeArticle(
                            slug=final_slug,
                            title=title,
                            excerpt=payload.get("excerpt") or "",
                            body_md=payload.get("body_md") or "",
                            meta_description=(payload.get("meta_description") or "")[:320] or None,
                            category=art_cat,
                            tags=(payload.get("tags") or "").strip() or None,
                            sort_order=0,
                            workflow_status=STATUS_PENDING_REVIEW,
                            is_published=False,
                            published_at=None,
                            seed_keyword=kw_s,
                            research_summary=(payload.get("research_summary") or "").strip() or None,
                            source_kind="ai_gallery",
                            source_note=(
                                "Google Search grounding"
                                if payload.get("search_grounding_used")
                                else "Gemini (search fallback)"
                            ),
                        )
                    )
                    db.commit()
                    log_ai_usage_event(
                        user_id=job.admin_user_id,
                        stage="kb_gallery",
                        request_kind="kb_gallery",
                        model_id=payload.get("model_id"),
                        input_tokens=payload.get("input_tokens"),
                        output_tokens=payload.get("output_tokens"),
                        agent_key="gallery_writer",
                    )
                    job.ok_count = int(job.ok_count or 0) + 1
                except Exception as exc:
                    db.rollback()
                    job.fail_count = int(job.fail_count or 0) + 1
                    _append_error(job, f"{kw_s}: {exc}")
                    _log.warning("kb batch keyword failed %s: %s", kw_s, exc)
                job.updated_at = datetime.utcnow()
                db.commit()

        job.current_keyword = None
        job.status = STATUS_DONE if int(job.ok_count or 0) > 0 or not keywords else STATUS_FAILED
        if int(job.ok_count or 0) == 0 and int(job.fail_count or 0) > 0:
            job.status = STATUS_FAILED
        job.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        _log.exception("kb gallery batch job %s crashed", job_id)
        try:
            job = db.query(models.KbGalleryBatchJob).filter(models.KbGalleryBatchJob.id == job_id).first()
            if job:
                job.status = STATUS_FAILED
                _append_error(job, "batch_job_crashed")
                job.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def create_batch_job(
    db,
    *,
    admin_user_id: int,
    keywords_raw: str,
    reference_notes: str,
    category_default: str,
) -> models.KbGalleryBatchJob:
    keywords = parse_keyword_lines(keywords_raw)
    job = models.KbGalleryBatchJob(
        admin_user_id=admin_user_id,
        status=STATUS_RUNNING,
        keywords_json=json.dumps(keywords, ensure_ascii=False),
        reference_notes=(reference_notes or "").strip() or None,
        category_default=category_default,
        ok_count=0,
        fail_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
