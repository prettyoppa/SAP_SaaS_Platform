"""요청 워크플로 단계별 — 비식별·일반화 KB 초안 자동 축적."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
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

_CODELIB_PRIVACY_RULES = """
- NEVER mention or expose the admin **code gallery** (코드갤러리), **code library**, **codelib**, `/codelib`, or internal reference-code catalog.
- NEVER reproduce proprietary snippets from that catalog; describe SAP patterns in your own words only.
"""

_FORBIDDEN_PUBLIC_MARKERS = (
    "코드갤러리",
    "code gallery",
    "codelib",
    "/codelib",
    "code library",
    "abapcode",
    "reference catalog",
    "internal catalog",
)

_backfill_lock = threading.Lock()
_backfill_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total_steps": 0,
    "done_steps": 0,
    "skipped_steps": 0,
    "errors": [],
    "last": None,
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


def _redact_code_fences(text: str | None) -> str:
    """납품·제안서에 포함된 ABAP/소스 블록은 패턴 설명만 남기도록 제거."""
    t = (text or "").strip()
    if not t:
        return ""
    return re.sub(r"```[\s\S]*?```", "\n[소스 코드는 공개 KB에 포함하지 않음 — 설계 패턴만 서술]\n", t)


def _payload_passes_codelib_guard(payload: dict[str, str]) -> bool:
    blob = " ".join(str(payload.get(k) or "") for k in ("title", "excerpt", "meta_description", "body_md", "tags")).lower()
    for marker in _FORBIDDEN_PUBLIC_MARKERS:
        if marker in blob:
            _log.warning("kb_request_flow: blocked output mentioning forbidden marker %r", marker)
            return False
    return True


def stages_available_for_request(db, request_kind: str, request_id: int) -> list[str]:
    """요청 데이터 기준으로 KB에 반영 가능한 단계 목록 (순서 고정)."""
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    stages: list[str] = []
    if kind == "rfp":
        row = db.query(models.RFP).filter(models.RFP.id == rid).first()
        if not row or (row.status or "").strip().lower() == "draft":
            return []
        if (row.proposal_text or "").strip():
            stages.append("proposal")
        if (row.fs_status or "").strip() == "ready" and (row.fs_text or "").strip():
            stages.append("functional_spec")
        if (row.delivered_code_status or "").strip() == "ready":
            stages.append("delivery")
        return stages
    if kind == "analysis":
        row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
        if not row or bool(getattr(row, "is_draft", False)):
            return []
        if (row.proposal_text or "").strip():
            stages.append("proposal")
        if (row.fs_status or "").strip() == "ready" and (getattr(row, "fs_text", None) or "").strip():
            stages.append("functional_spec")
        if (getattr(row, "delivered_code_status", None) or "").strip() == "ready":
            stages.append("delivery")
        return stages
    if kind == "integration":
        row = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == rid).first()
        if not row:
            return []
        if (row.proposal_text or "").strip():
            stages.append("proposal")
        if (row.fs_status or "").strip() == "ready" and (getattr(row, "fs_text", None) or "").strip():
            stages.append("functional_spec")
        if (getattr(row, "delivered_code_status", None) or "").strip() == "ready":
            stages.append("delivery")
        return stages
    return stages


def collect_backfill_targets(db) -> list[tuple[str, int, list[str]]]:
    """일괄 백필 대상: (request_kind, request_id, stages)."""
    out: list[tuple[str, int, list[str]]] = []
    for row in db.query(models.RFP).order_by(models.RFP.id.asc()).all():
        stages = stages_available_for_request(db, "rfp", int(row.id))
        if stages:
            out.append(("rfp", int(row.id), stages))
    for row in db.query(models.AbapAnalysisRequest).order_by(models.AbapAnalysisRequest.id.asc()).all():
        stages = stages_available_for_request(db, "analysis", int(row.id))
        if stages:
            out.append(("analysis", int(row.id), stages))
    for row in db.query(models.IntegrationRequest).order_by(models.IntegrationRequest.id.asc()).all():
        stages = stages_available_for_request(db, "integration", int(row.id))
        if stages:
            out.append(("integration", int(row.id), stages))
    return out


def backfill_status_snapshot() -> dict[str, Any]:
    with _backfill_lock:
        return dict(_backfill_state)


def run_request_flow_backfill(*, force: bool = True) -> None:
    """기존 요청 전건 — 단계별 KB 초안 일괄 생성 (백그라운드 1회 실행)."""
    delay = float(os.environ.get("KB_REQUEST_FLOW_BACKFILL_DELAY_SEC") or "2")
    with _backfill_lock:
        if _backfill_state.get("running"):
            return
        _backfill_state.update(
            {
                "running": True,
                "started_at": datetime.utcnow().isoformat(),
                "finished_at": None,
                "total_steps": 0,
                "done_steps": 0,
                "skipped_steps": 0,
                "errors": [],
                "last": None,
            }
        )

    from .database import SessionLocal

    db = SessionLocal()
    try:
        targets = collect_backfill_targets(db)
        total = sum(len(stages) for _k, _i, stages in targets)
        with _backfill_lock:
            _backfill_state["total_steps"] = total
    finally:
        db.close()

    try:
        for kind, rid, stages in targets:
            for stage in stages:
                label = f"{kind}:{rid}:{stage}"
                with _backfill_lock:
                    _backfill_state["last"] = label
                try:
                    ok = run_request_kb_flow(kind, rid, stage, force=force)
                    with _backfill_lock:
                        if ok:
                            _backfill_state["done_steps"] = int(_backfill_state.get("done_steps") or 0) + 1
                        else:
                            _backfill_state["skipped_steps"] = int(_backfill_state.get("skipped_steps") or 0) + 1
                except Exception as ex:
                    with _backfill_lock:
                        errs = list(_backfill_state.get("errors") or [])
                        errs.append(f"{label}: {type(ex).__name__}")
                        _backfill_state["errors"] = errs[-50:]
                    _log.exception("kb_request_flow backfill failed at %s", label)
                if delay > 0:
                    time.sleep(delay)
    finally:
        with _backfill_lock:
            _backfill_state["running"] = False
            _backfill_state["finished_at"] = datetime.utcnow().isoformat()


def schedule_request_flow_backfill(*, force: bool = True) -> bool:
    """백필 작업 시작. 이미 실행 중이면 False."""
    with _backfill_lock:
        if _backfill_state.get("running"):
            return False
    threading.Thread(
        target=run_request_flow_backfill,
        kwargs={"force": force},
        daemon=True,
        name="kb-request-flow-backfill",
    ).start()
    return True


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
            "proposal_excerpt": _truncate(_redact_code_fences(row.proposal_text), 2800),
            "fs_excerpt": _truncate(_redact_code_fences(row.fs_text), 2000),
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
            "proposal_excerpt": _truncate(_redact_code_fences(row.proposal_text), 2800),
            "fs_excerpt": _truncate(_redact_code_fences(getattr(row, "fs_text", None)), 2000),
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
            "proposal_excerpt": _truncate(_redact_code_fences(row.proposal_text), 2800),
            "fs_excerpt": _truncate(_redact_code_fences(getattr(row, "fs_text", None)), 2000),
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
{_CODELIB_PRIVACY_RULES}

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
{_CODELIB_PRIVACY_RULES}

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
    if not _payload_passes_codelib_guard(payload):
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


def run_request_kb_flow(request_kind: str, request_id: int, stage: str, *, force: bool = False) -> bool:
    """Background worker: one stage → KB draft or append. 성공 시 True."""
    if not force and not request_flow_enabled():
        return False
    kind = (request_kind or "").strip().lower()
    st = (stage or "").strip().lower()
    if kind not in _VALID_KINDS or st not in _VALID_STAGES:
        return False

    from .database import SessionLocal

    db = SessionLocal()
    try:
        ctx = _load_request_context(db, kind, int(request_id))
        if not ctx:
            return False

        fkey = flow_key(kind, int(request_id))
        article = (
            db.query(models.KnowledgeArticle)
            .filter(models.KnowledgeArticle.request_flow_key == fkey)
            .first()
        )
        if article:
            note = _parse_source_note(article.source_note)
            if st in _stages_done(note):
                return False
            existing_body = article.body_md
        else:
            existing_body = None

        payload = _generate_article_fields(ctx=ctx, stage=st, existing_body=existing_body)
        if not payload:
            return False

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
        return True
    except Exception:
        db.rollback()
        _log.exception("kb_request_flow failed kind=%s id=%s stage=%s", kind, request_id, st)
        return False
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
