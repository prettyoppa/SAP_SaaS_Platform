"""Korean site copy → English with SiteSettings-backed cache (Gemini)."""

from __future__ import annotations

import hashlib
import logging
import os
import re

import google.generativeai as genai
from sqlalchemy.orm import Session

from . import models
from .gemini_model import get_gemini_model_id

_log = logging.getLogger(__name__)

_CACHE_PREFIX = "locale_auto_en:"
_MAX_SOURCE_LEN = 24_000
_MAX_OUT = 8192

_APP_INTRO = """You translate Korean content for "SAP Dev Hub" (Catchy Lab), a SaaS platform for SAP ABAP RFPs, AI interviews, proposals, and delivery.
Tone: natural, professional English. Keep SAP/ABAP terms. Preserve Markdown structure and HTML tags (<br>, etc.) exactly where present."""


def _cache_setting_key(namespace: str, ko_text: str) -> str:
    digest = hashlib.sha256((ko_text or "").encode("utf-8")).hexdigest()[:24]
    safe_ns = re.sub(r"[^a-zA-Z0-9_.-]", "_", (namespace or "text"))[:80]
    return f"{_CACHE_PREFIX}{safe_ns}:{digest}"


def _read_cache(db: Session, cache_key: str) -> str:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == cache_key).first()
    return (row.value or "").strip() if row else ""


def read_cached_translation(db: Session, ko: str, *, namespace: str) -> str:
    """저장된 locale_auto_en 캐시만 조회(Gemini 호출 없음)."""
    source = (ko or "").strip()
    if not source:
        return ""
    return _read_cache(db, _cache_setting_key(namespace, source))


def _write_cache(db: Session, cache_key: str, translated: str) -> None:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == cache_key).first()
    if row:
        row.value = translated
    else:
        db.add(models.SiteSettings(key=cache_key, value=translated))
    db.commit()


def _gemini_translate(*, ko: str, purpose: str) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(get_gemini_model_id())
    prompt = f"""{_APP_INTRO}

**Context:** {purpose}

**Korean source:**
{ko}

**Rules:**
- Return only the English translation (no preamble).
- Match length/register: short titles stay short; markdown lists/headings stay markdown.
- Do not add facts not present in the Korean source.
"""
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=_MAX_OUT,
            temperature=0.2,
        ),
    )
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty_model_output")
    text = re.sub(r'^["\']|["\']$', "", text.strip())
    return text


def get_or_translate_ko_to_en(
    db: Session,
    ko: str,
    *,
    namespace: str,
    purpose: str = "",
) -> str:
    """Return English text; uses cache; falls back to Korean if translation unavailable."""
    source = (ko or "").strip()
    if not source:
        return ""
    if len(source) > _MAX_SOURCE_LEN:
        _log.warning("locale_auto_translate: source too long for %s (%s chars)", namespace, len(source))
        return source

    cache_key = _cache_setting_key(namespace, source)
    cached = _read_cache(db, cache_key)
    if cached:
        return cached

    try:
        translated = _gemini_translate(ko=source, purpose=purpose or namespace)
        _write_cache(db, cache_key, translated)
        return translated
    except Exception:
        _log.exception("locale_auto_translate failed namespace=%s", namespace)
        return source
