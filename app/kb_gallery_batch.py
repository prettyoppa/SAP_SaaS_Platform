"""지식갤러리 — 키워드·키노트 일괄 초안 생성 백그라운드 작업."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from . import models
from .ai_usage_recorder import AiUsageContext, ai_usage_scope, log_ai_usage_event
from .database import SessionLocal
from .kb_article_generator import (
    SOURCE_MODE_KEYNOTE,
    SOURCE_MODE_KEYWORDS,
    finalize_kb_draft_payload,
    generate_kb_draft_from_keynote,
    generate_kb_draft_from_keyword,
    normalize_source_mode,
    parse_keyword_lines,
)
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


def _save_draft_article(
    db,
    *,
    job: models.KbGalleryBatchJob,
    payload: dict,
    cat: str,
    seed: str,
    source_note: str,
) -> None:
    title = payload["title"]
    base_slug = slugify_kb_title(title) or slugify_kb_title(seed)
    final_slug = ensure_unique_kb_slug(db, base_slug)
    art_cat = payload.get("category") or cat
    if art_cat not in KB_CATEGORIES:
        art_cat = cat
    db.add(
        models.KnowledgeArticle(
            slug=final_slug,
            title=title,
            title_en=(payload.get("title_en") or "").strip() or None,
            excerpt=payload.get("excerpt") or "",
            excerpt_en=(payload.get("excerpt_en") or "").strip() or None,
            body_md=payload.get("body_md") or "",
            body_md_en=(payload.get("body_md_en") or "").strip() or None,
            body_format=(payload.get("body_format") or "markdown").strip().lower(),
            body_format_en=(payload.get("body_format_en") or "").strip() or None,
            body_screenshots_json=None,
            meta_description=(payload.get("meta_description") or "")[:320] or None,
            meta_description_en=(payload.get("meta_description_en") or "").strip()[:320] or None,
            category=art_cat,
            tags=(payload.get("tags") or "").strip() or None,
            sort_order=0,
            workflow_status=STATUS_PENDING_REVIEW,
            is_published=False,
            published_at=None,
            seed_keyword=(seed or "")[:200] or None,
            research_summary=(payload.get("research_summary") or "").strip() or None,
            source_kind="ai_gallery",
            source_note=source_note,
        )
    )
    db.commit()


def _progress_label_keynote(note: str) -> str:
    first = ""
    for line in (note or "").split("\n"):
        s = line.strip()
        if s:
            first = s
            break
    if first:
        return first[:80]
    return "키노트"


def run_kb_gallery_batch_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(models.KbGalleryBatchJob).filter(models.KbGalleryBatchJob.id == job_id).first()
        if not job:
            return
        mode = normalize_source_mode(getattr(job, "source_mode", None))
        ref_notes = (job.reference_notes or "").strip()
        cat = (job.category_default or "general").strip().lower()
        if cat not in KB_CATEGORIES:
            cat = "general"
        also_en = bool(getattr(job, "also_english", False))

        job.status = STATUS_RUNNING
        job.updated_at = datetime.utcnow()
        db.commit()

        with ai_usage_scope(
            AiUsageContext(user_id=job.admin_user_id, request_kind="kb_gallery")
        ):
            if mode == SOURCE_MODE_KEYNOTE:
                note = (job.keynote_text or "").strip()
                if not note:
                    _append_error(job, "keynote: empty")
                    job.status = STATUS_FAILED
                    job.updated_at = datetime.utcnow()
                    db.commit()
                    return
                job.current_keyword = _progress_label_keynote(note)
                job.updated_at = datetime.utcnow()
                db.commit()
                try:
                    payload = generate_kb_draft_from_keynote(
                        keynote=note,
                        reference_notes=ref_notes,
                        category_hint=cat,
                    )
                    finalize_kb_draft_payload(
                        payload,
                        also_english=also_en,
                        body_format="markdown",
                        reference_notes=ref_notes,
                    )
                    _save_draft_article(
                        db,
                        job=job,
                        payload=payload,
                        cat=cat,
                        seed=payload.get("seed_keyword") or "키노트",
                        source_note=(
                            "Keynote AI draft (Google Search grounding)"
                            if payload.get("search_grounding_used")
                            else "Keynote AI draft (Gemini fallback)"
                        ),
                    )
                    log_ai_usage_event(
                        user_id=job.admin_user_id,
                        stage="kb_gallery",
                        request_kind="kb_gallery",
                        model_id=payload.get("model_id"),
                        input_tokens=payload.get("input_tokens"),
                        output_tokens=payload.get("output_tokens"),
                        agent_key="gallery_writer",
                    )
                    job.ok_count = 1
                except Exception as exc:
                    db.rollback()
                    job.fail_count = 1
                    _append_error(job, f"keynote: {exc}")
                    _log.warning("kb batch keynote failed: %s", exc)
            else:
                try:
                    keywords = json.loads(job.keywords_json or "[]")
                except Exception:
                    keywords = []
                if not isinstance(keywords, list):
                    keywords = []
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
                        finalize_kb_draft_payload(
                            payload,
                            also_english=also_en,
                            body_format="markdown",
                            reference_notes=ref_notes,
                        )
                        _save_draft_article(
                            db,
                            job=job,
                            payload=payload,
                            cat=cat,
                            seed=kw_s,
                            source_note=(
                                "Google Search grounding"
                                if payload.get("search_grounding_used")
                                else "Gemini (search fallback)"
                            ),
                        )
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
        if mode == SOURCE_MODE_KEYNOTE:
            has_work = bool((job.keynote_text or "").strip())
        else:
            try:
                kw_list = json.loads(job.keywords_json or "[]")
                has_work = isinstance(kw_list, list) and len(kw_list) > 0
            except Exception:
                has_work = False
        job.status = STATUS_DONE if int(job.ok_count or 0) > 0 or not has_work else STATUS_FAILED
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
    source_mode: str = SOURCE_MODE_KEYWORDS,
    also_english: bool = False,
    keywords_raw: str = "",
    keynote_text: str = "",
    reference_notes: str,
    category_default: str,
) -> models.KbGalleryBatchJob:
    mode = normalize_source_mode(source_mode)
    kw_json = "[]"
    note_stored: str | None = None
    if mode == SOURCE_MODE_KEYNOTE:
        note_stored = (keynote_text or "").strip() or None
    else:
        keywords = parse_keyword_lines(keywords_raw)
        kw_json = json.dumps(keywords, ensure_ascii=False)
    job = models.KbGalleryBatchJob(
        admin_user_id=admin_user_id,
        status=STATUS_RUNNING,
        source_mode=mode,
        also_english=bool(also_english),
        keywords_json=kw_json,
        keynote_text=note_stored,
        reference_notes=(reference_notes or "").strip() or None,
        category_default=category_default,
        ok_count=0,
        fail_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def batch_job_total_items(job: models.KbGalleryBatchJob) -> int:
    mode = normalize_source_mode(getattr(job, "source_mode", None))
    if mode == SOURCE_MODE_KEYNOTE:
        return 1 if (job.keynote_text or "").strip() else 0
    try:
        keywords = json.loads(job.keywords_json or "[]")
        return len(keywords) if isinstance(keywords, list) else 0
    except Exception:
        return 0
