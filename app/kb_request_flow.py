"""요청 워크플로 단계별 — 비식별·일반화 KB 초안 자동 축적."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any

from . import models
from .delivered_code_package import extract_json_object_from_llm_text
from .gemini_model import get_gemini_model_id
from .kb_article_generator import _call_gemini_plain, _normalize_article_payload
from .kb_public_content import sanitize_meta_description
from .kb_slug import ensure_unique_kb_slug, slugify_kb_title
from .kb_workflow import STATUS_PENDING_REVIEW, approve_article, sync_publish_flags

_log = logging.getLogger(__name__)

SOURCE_KIND = "request_flow"
_VALID_KINDS = frozenset({"rfp", "analysis", "integration"})
_VALID_STAGES = frozenset({"proposal", "functional_spec", "delivery"})

_STAGE_HEADING_KO = {
    "proposal": "개발 제안 단계",
    "functional_spec": "기능명세(FS) 단계",
    "delivery": "납품·구현 단계",
}

_CATEGORY_BY_KIND = {
    "rfp": "abap",
    "analysis": "analysis",
    "integration": "integration",
}

_ARTICLE_JSON_HINT = """
Respond with a single JSON object only (no markdown fence), keys:
- title (string, Korean, SEO-friendly generic topic — no company or person names, max 120 chars)
- excerpt (string, Korean, 1-2 sentences)
- meta_description (string, Korean, max 155 chars, no URLs)
- body_md (string, Korean markdown 400-1200 words; use ## section headings; educational tone)
- tags (string, comma-separated lowercase SAP keywords)
- category (one of: general, abap, analysis, integration)
"""


def request_flow_enabled() -> bool:
    return (os.environ.get("KB_REQUEST_FLOW_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def request_flow_auto_publish() -> bool:
    return (os.environ.get("KB_REQUEST_FLOW_AUTO_PUBLISH") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def flow_key(request_kind: str, request_id: int) -> str:
    kind = (request_kind or "").strip().lower()
    return f"{kind}:{int(request_id)}"


def _parse_source_note(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _stages_done(note: dict[str, Any]) -> set[str]:
    raw = note.get("stages") or []
    if not isinstance(raw, list):
        return set()
    return {str(s).strip().lower() for s in raw if str(s).strip()}


def _truncate(text: str | None, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _owner_is_test(db, user_id: int | None) -> bool:
    if not user_id:
        return False
    u = db.query(models.User).filter(models.User.id == int(user_id)).first()
    return bool(u and getattr(u, "is_test_account", False))


def _load_request_context(db, request_kind: str, request_id: int) -> dict[str, Any] | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        row = db.query(models.RFP).filter(models.RFP.id == rid).first()
        if not row:
            return None
        return {
            "request_kind": kind,
            "request_id": rid,
            "owner_user_id": int(row.user_id),
            "category_hint": _CATEGORY_BY_KIND[kind],
            "topic_hint": (row.title or "").strip(),
            "modules": (row.sap_modules or "").strip(),
            "dev_types": (row.dev_types or "").strip(),
            "proposal_excerpt": _truncate(row.proposal_text, 2800),
            "fs_excerpt": _truncate(row.fs_text, 2000),
            "delivery_note": _truncate((row.delivered_code_status or ""), 80),
            "impl_types": "",
        }
    if kind == "analysis":
        row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
        if not row:
            return None
        title = (getattr(row, "title", None) or "").strip() or "ABAP 분석·개선"
        return {
            "request_kind": kind,
            "request_id": rid,
            "owner_user_id": int(row.user_id),
            "category_hint": _CATEGORY_BY_KIND[kind],
            "topic_hint": title,
            "modules": (getattr(row, "sap_modules", None) or "").strip(),
            "dev_types": "",
            "proposal_excerpt": _truncate(row.proposal_text, 2800),
            "fs_excerpt": _truncate(getattr(row, "fs_text", None), 2000),
            "delivery_note": _truncate((getattr(row, "delivered_code_status", None) or ""), 80),
            "impl_types": "",
        }
    if kind == "integration":
        row = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == rid).first()
        if not row:
            return None
        return {
            "request_kind": kind,
            "request_id": rid,
            "owner_user_id": int(row.user_id),
            "category_hint": _CATEGORY_BY_KIND[kind],
            "topic_hint": (row.title or "").strip(),
            "modules": (row.sap_modules or "").strip(),
            "dev_types": (getattr(row, "impl_types", None) or "").strip(),
            "proposal_excerpt": _truncate(row.proposal_text, 2800),
            "fs_excerpt": _truncate(getattr(row, "fs_text", None), 2000),
            "delivery_note": _truncate((getattr(row, "delivered_code_status", None) or ""), 80),
            "impl_types": (getattr(row, "impl_types", None) or "").strip(),
        }
    return None


def _stage_payload(ctx: dict[str, Any], stage: str) -> str:
    st = (stage or "").strip().lower()
    lines = [
        f"Workflow stage: {st} ({_STAGE_HEADING_KO.get(st, st)})",
        f"Request channel: {ctx.get('request_kind')}",
        f"Topic hint (generalize — do NOT copy verbatim if it looks like a private project name): {ctx.get('topic_hint')}",
        f"SAP modules (if any): {ctx.get('modules') or '—'}",
        f"Dev / impl types (if any): {ctx.get('dev_types') or ctx.get('impl_types') or '—'}",
    ]
    if st == "proposal":
        lines.append(f"Proposal excerpt (redact all PII before writing):\n{ctx.get('proposal_excerpt') or '—'}")
    elif st == "functional_spec":
        lines.append(f"FS excerpt (redact all PII):\n{ctx.get('fs_excerpt') or '—'}")
    elif st == "delivery":
        lines.append(
            "Delivery status note (describe patterns only — never paste source code): "
            + (ctx.get("delivery_note") or "ready")
        )
    return "\n".join(lines)


def _build_prompt(*, ctx: dict[str, Any], stage: str, existing_body: str | None) -> str:
    stage_block = _stage_payload(ctx, stage)
    existing = (existing_body or "").strip()
    if existing:
        return f"""You are an expert SAP technical writer. Update a PUBLIC knowledge-base article using new workflow stage notes.

**Strict privacy rules:**
- Remove ALL company names, person names, emails, phone numbers, internal project names, and client identifiers.
- Do NOT quote member request text verbatim; synthesize generic SAP practitioner guidance.
- Do NOT include source code, file paths, or credentials.
- Focus on searchable SAP keywords (ABAP, ALV, RFC, IDoc, BAPI, S/4HANA, etc.).

**Existing article body (markdown):**
{existing}

**New stage notes to incorporate as a new ## section:**
{stage_block}

**Task:** Return JSON with the FULL updated body_md (existing content preserved + new ## {_STAGE_HEADING_KO.get(stage, stage)} section).
Also refresh title/excerpt/meta_description/tags if the new stage adds important keywords.
{_ARTICLE_JSON_HINT}
"""
    return f"""You are an expert SAP technical writer. Create a NEW public knowledge-base article from internal workflow notes.

**Strict privacy rules:**
- Remove ALL company names, person names, emails, phone numbers, internal project names, and client identifiers.
- Do NOT quote member request text verbatim; synthesize generic SAP practitioner guidance.
- Do NOT include source code, file paths, or credentials.
- Focus on searchable SAP keywords useful on Google/Naver.

**Workflow notes (stage: {stage}):**
{stage_block}

**Task:** Write an original educational article for SAP developers. Start body with ## sections (no duplicate H1 title line).
{_ARTICLE_JSON_HINT}
"""


def _generate_article_fields(
    *,
    ctx: dict[str, Any],
    stage: str,
    existing_body: str | None,
) -> dict[str, str] | None:
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        _log.warning("kb_request_flow: GOOGLE_API_KEY missing — skip")
        return None
    model_id = get_gemini_model_id()
    prompt = _build_prompt(ctx=ctx, stage=stage, existing_body=existing_body)
    try:
        raw, _usage = _call_gemini_plain(prompt=prompt, api_key=api_key, model_id=model_id)
    except Exception:
        _log.exception(
            "kb_request_flow: LLM call failed kind=%s id=%s stage=%s",
            ctx.get("request_kind"),
            ctx.get("request_id"),
            stage,
        )
        return None
    data = extract_json_object_from_llm_text(raw)
    if not data:
        _log.warning(
            "kb_request_flow: invalid JSON kind=%s id=%s stage=%s",
            ctx.get("request_kind"),
            ctx.get("request_id"),
            stage,
        )
        return None
    keyword = (str(data.get("title") or ctx.get("topic_hint") or "SAP")).strip()
    payload = _normalize_article_payload(data, keyword=keyword, research="")
    if not payload.get("body_md"):
        return None
    return payload


def _apply_article_fields(article: models.KnowledgeArticle, payload: dict[str, str], *, stage: str) -> None:
    article.title = payload["title"]
    article.excerpt = payload.get("excerpt") or ""
    article.meta_description = payload.get("meta_description") or sanitize_meta_description(article.excerpt)
    article.body_md = payload["body_md"]
    article.tags = payload.get("tags") or ""
    cat = (payload.get("category") or article.category or "general").strip().lower()
    if cat in {"general", "abap", "analysis", "integration"}:
        article.category = cat
    note = _parse_source_note(article.source_note)
    note["stages"] = sorted(_stages_done(note) | {stage})
    article.source_note = json.dumps(note, ensure_ascii=False)
    article.updated_at = datetime.utcnow()


def run_request_kb_flow(request_kind: str, request_id: int, stage: str) -> None:
    """Background worker: one stage → KB draft or append."""
    if not request_flow_enabled():
        return
    kind = (request_kind or "").strip().lower()
    st = (stage or "").strip().lower()
    if kind not in _VALID_KINDS or st not in _VALID_STAGES:
        return

    from .database import SessionLocal

    db = SessionLocal()
    try:
        ctx = _load_request_context(db, kind, int(request_id))
        if not ctx:
            return
        if _owner_is_test(db, ctx.get("owner_user_id")):
            return

        fkey = flow_key(kind, int(request_id))
        article = (
            db.query(models.KnowledgeArticle)
            .filter(models.KnowledgeArticle.request_flow_key == fkey)
            .first()
        )
        if article:
            note = _parse_source_note(article.source_note)
            if st in _stages_done(note):
                return
            existing_body = article.body_md
        else:
            existing_body = None

        payload = _generate_article_fields(ctx=ctx, stage=st, existing_body=existing_body)
        if not payload:
            return

        if article:
            _apply_article_fields(article, payload, stage=st)
            db.add(article)
        else:
            base_slug = slugify_kb_title(payload["title"], fallback="sap-insight")
            slug = ensure_unique_kb_slug(db, base_slug)
            note = {
                "stages": [st],
                "request_kind": kind,
                "request_id": int(request_id),
            }
            article = models.KnowledgeArticle(
                slug=slug,
                title=payload["title"],
                excerpt=payload.get("excerpt") or "",
                meta_description=payload.get("meta_description") or "",
                body_md=payload["body_md"],
                tags=payload.get("tags") or "",
                category=(payload.get("category") or _CATEGORY_BY_KIND.get(kind, "general")),
                source_kind=SOURCE_KIND,
                source_note=json.dumps(note, ensure_ascii=False),
                request_flow_key=fkey,
                seed_keyword=_truncate(ctx.get("topic_hint"), 200),
                workflow_status=STATUS_PENDING_REVIEW,
                is_published=False,
            )
            if request_flow_auto_publish():
                approve_article(article)
            else:
                sync_publish_flags(article)
            db.add(article)

        db.commit()
        _log.info(
            "kb_request_flow: article id=%s key=%s stage=%s published=%s",
            article.id,
            fkey,
            st,
            article.is_published,
        )
    except Exception:
        db.rollback()
        _log.exception("kb_request_flow failed kind=%s id=%s stage=%s", kind, request_id, st)
    finally:
        db.close()


def schedule_request_kb_flow(request_kind: str, request_id: int, stage: str) -> None:
    if not request_flow_enabled():
        return
    threading.Thread(
        target=run_request_kb_flow,
        args=(request_kind, int(request_id), stage),
        daemon=True,
        name=f"kb-flow-{request_kind}-{request_id}-{stage}",
    ).start()
