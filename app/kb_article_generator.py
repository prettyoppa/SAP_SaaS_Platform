"""SAP 지식갤러리 — 키워드 기반 초안 생성 (Gemini + Google Search grounding)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .delivered_code_package import extract_json_object_from_llm_text
from .kb_public_content import sanitize_meta_description, strip_leading_title_from_body_md
from .gemini_model import get_gemini_model_id

_log = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_MAX_KEYWORDS_PER_BATCH = 5
_MAX_KEYNOTE_CHARS = 16000
_MIN_KEYNOTE_CHARS = 20
_VALID_CATEGORIES = frozenset({"general", "abap", "analysis", "integration"})
SOURCE_MODE_KEYWORDS = "keywords"
SOURCE_MODE_KEYNOTE = "keynote"

_ARTICLE_JSON_SCHEMA_HINT = """
Respond with a single JSON object only (no markdown fence), keys:
- title (string, Korean, SEO-friendly, max 120 chars)
- excerpt (string, Korean, 1-2 sentences for list card)
- meta_description (string, Korean, max 155 chars for Google snippet — no URLs)
- body_md (string, Korean markdown 800-1500 words: start with ## section headings only — do NOT repeat the title as # or H1 at the top)
- tags (string, comma-separated, lowercase)
- category (one of: general, abap, analysis, integration)
- research_notes (string, Korean: 3-5 bullet points citing what you learned from search — URLs or doc names if known)
"""


def normalize_source_mode(raw: str | None) -> str:
    s = (raw or SOURCE_MODE_KEYWORDS).strip().lower()
    return s if s in (SOURCE_MODE_KEYWORDS, SOURCE_MODE_KEYNOTE) else SOURCE_MODE_KEYWORDS


def parse_keynote_text(raw: str, *, max_chars: int = _MAX_KEYNOTE_CHARS) -> str:
    text = (raw or "").replace("\r\n", "\n").strip()
    if len(text) < _MIN_KEYNOTE_CHARS:
        raise ValueError("keynote_too_short")
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def keynote_seed_label(keynote: str) -> str:
    for line in (keynote or "").split("\n"):
        s = line.strip()
        if s:
            return s[:200]
    return "키노트"


def parse_keyword_lines(raw: str, *, max_count: int = _MAX_KEYWORDS_PER_BATCH) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in (raw or "").replace("\r", "\n").split("\n"):
        kw = line.strip()
        if not kw or kw in seen:
            continue
        seen.add(kw)
        out.append(kw[:200])
        if len(out) >= max_count:
            break
    return out


def _build_prompt(*, keyword: str, reference_notes: str, category_hint: str) -> str:
    ref = (reference_notes or "").strip()
    cat = (category_hint or "general").strip().lower()
    if cat not in _VALID_CATEGORIES:
        cat = "general"
    ref_block = f"\n\n**Admin reference notes (must respect):**\n{ref}\n" if ref else ""
    return f"""You are an expert SAP technical writer for "Catch Lab SAP Dev Hub" knowledge gallery.

**Task:** Use Google Search to find current, credible SAP-related information, then write an original Korean article for the keyword below. Do not copy text verbatim; synthesize for practitioners.

**Keyword / topic:** {keyword}
**Preferred category:** {cat}
{ref_block}
**Rules:**
- Search the web for SAP Help, SAP Community, official docs, and reputable technical sources before writing.
- Focus on S/4HANA and ECC where relevant; note version differences when important.
- No fabricated transaction codes or Note numbers — only include if found in search results.
- Practical tone; include checklists or steps where useful.
- Do not mention Catch Lab internal systems or member request data.
{_ARTICLE_JSON_SCHEMA_HINT}
"""


def _build_keynote_prompt(*, keynote: str, reference_notes: str, category_hint: str) -> str:
    ref = (reference_notes or "").strip()
    cat = (category_hint or "general").strip().lower()
    if cat not in _VALID_CATEGORIES:
        cat = "general"
    ref_block = (
        f"\n\n**Admin instructions (must respect):**\n{ref}\n" if ref else ""
    )
    return f"""You are an expert SAP technical writer for "Catch Lab SAP Dev Hub" knowledge gallery.

**Task:** The admin pasted a personal WORK KEYNOTE — shorthand bullets, keywords, and fragments from daily work. It is NOT a finished public article. Treat the entire block below as ONE note.

Your job:
1. Preserve the keynote's topics, intent, and factual claims (do not drop angles the author recorded).
2. Expand into ONE polished Korean knowledge-base article suitable for public readers and search (SAP practitioners).
3. Use Google Search to verify or fill gaps where the keynote is thin; do not replace the author's focus with unrelated generic content.
4. Do not invent transaction codes, Note numbers, or version facts unless found in search or clearly implied by the keynote.
5. Do not mention Catch Lab internal systems or member request data.

**Work keynote (primary source):**
{keynote}

**Preferred category:** {cat}
{ref_block}
**Rules:**
- Output language: Korean for title, excerpt, meta_description, body_md, research_notes.
- Practical tone; structure with ## section headings in body_md (no duplicate H1 title at top of body).
{_ARTICLE_JSON_SCHEMA_HINT}
"""


def _extract_grounding_notes(response: Any) -> str:
    """검색 grounding 메타데이터 → 관리자용 메모."""
    lines: list[str] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates[:1]:
            gm = getattr(cand, "grounding_metadata", None)
            if gm is None:
                continue
            chunks = getattr(gm, "grounding_chunks", None) or []
            for ch in chunks[:8]:
                web = getattr(ch, "web", None)
                if web is None:
                    continue
                title = (getattr(web, "title", None) or "").strip()
                uri = (getattr(web, "uri", None) or "").strip()
                if title or uri:
                    lines.append(f"- {title or uri}" + (f" ({uri})" if uri and title else ""))
            queries = getattr(gm, "web_search_queries", None) or []
            if queries:
                lines.insert(0, "검색 쿼리: " + ", ".join(str(q) for q in queries[:5]))
    except Exception:
        _log.debug("grounding metadata parse skipped", exc_info=True)
    return "\n".join(lines).strip()


def _call_gemini_with_search(*, prompt: str, api_key: str, model_id: str) -> tuple[str, str, dict[str, int | None]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        temperature=1.0,
        max_output_tokens=8192,
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=config,
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty_model_output")
    research = _extract_grounding_notes(response)
    usage = getattr(response, "usage_metadata", None)
    inp = getattr(usage, "prompt_token_count", None) if usage else None
    out = getattr(usage, "candidates_token_count", None) if usage else None
    return text, research, {"input_tokens": inp, "output_tokens": out}


def _call_gemini_plain(*, prompt: str, api_key: str, model_id: str) -> tuple[str, dict[str, int | None]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=8192,
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=config,
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty_model_output")
    usage = getattr(response, "usage_metadata", None)
    inp = getattr(usage, "prompt_token_count", None) if usage else None
    out = getattr(usage, "candidates_token_count", None) if usage else None
    return text, {"input_tokens": inp, "output_tokens": out}


def _normalize_article_payload(data: dict[str, Any], *, keyword: str, research: str) -> dict[str, str]:
    cat = (str(data.get("category") or "general")).strip().lower()
    if cat not in _VALID_CATEGORIES:
        cat = "general"
    tags = (str(data.get("tags") or "")).strip()[:512]
    notes = (str(data.get("research_notes") or "")).strip()
    combined_research = "\n\n".join(p for p in (research, notes) if p).strip()
    title = (str(data.get("title") or keyword)).strip()[:500]
    body_md = strip_leading_title_from_body_md(
        (str(data.get("body_md") or "")).strip(), title
    )
    meta_raw = (str(data.get("meta_description") or "")).strip()
    if not meta_raw:
        meta_raw = (str(data.get("excerpt") or "")).strip()
    return {
        "title": title,
        "excerpt": (str(data.get("excerpt") or "")).strip()[:2000],
        "meta_description": sanitize_meta_description(meta_raw, max_len=320),
        "body_md": body_md,
        "tags": tags,
        "category": cat,
        "research_summary": combined_research[:8000],
    }


def generate_kb_draft_from_keyword(
    *,
    keyword: str,
    reference_notes: str = "",
    category_hint: str = "general",
) -> dict[str, Any]:
    """
    키워드 1건 → 초안 필드 dict.
    Raises RuntimeError / ValueError on failure.
    """
    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("empty_keyword")
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    model_id = get_gemini_model_id()
    prompt = _build_prompt(keyword=kw, reference_notes=reference_notes, category_hint=category_hint)

    raw_text = ""
    research = ""
    usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    search_used = True
    try:
        raw_text, research, usage = _call_gemini_with_search(
            prompt=prompt, api_key=api_key, model_id=model_id
        )
    except Exception as exc:
        _log.warning("kb generate: search grounding failed, fallback plain: %s", exc)
        search_used = False
        raw_text, usage = _call_gemini_plain(prompt=prompt, api_key=api_key, model_id=model_id)
        research = f"(Google Search 연동 실패 — 모델 단독 초안)\n{exc}"[:2000]

    data = extract_json_object_from_llm_text(raw_text)
    if not data:
        raise RuntimeError("invalid_json_from_model")
    payload = _normalize_article_payload(data, keyword=kw, research=research)
    if not payload["body_md"]:
        raise RuntimeError("empty_body_from_model")
    payload["seed_keyword"] = kw
    payload["search_grounding_used"] = search_used
    payload["model_id"] = model_id
    payload["input_tokens"] = usage.get("input_tokens")
    payload["output_tokens"] = usage.get("output_tokens")
    return payload


def generate_kb_draft_from_keynote(
    *,
    keynote: str,
    reference_notes: str = "",
    category_hint: str = "general",
) -> dict[str, Any]:
    """업무 키노트 1건 → KB 공개 수준 초안 1건."""
    note = parse_keynote_text(keynote)
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    model_id = get_gemini_model_id()
    prompt = _build_keynote_prompt(
        keynote=note, reference_notes=reference_notes, category_hint=category_hint
    )

    raw_text = ""
    research = ""
    usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    search_used = True
    try:
        raw_text, research, usage = _call_gemini_with_search(
            prompt=prompt, api_key=api_key, model_id=model_id
        )
    except Exception as exc:
        _log.warning("kb keynote generate: search grounding failed, fallback plain: %s", exc)
        search_used = False
        raw_text, usage = _call_gemini_plain(prompt=prompt, api_key=api_key, model_id=model_id)
        research = f"(Google Search 연동 실패 — 모델 단독 초안)\n{exc}"[:2000]

    data = extract_json_object_from_llm_text(raw_text)
    if not data:
        raise RuntimeError("invalid_json_from_model")
    seed = keynote_seed_label(note)
    payload = _normalize_article_payload(data, keyword=seed, research=research)
    if not payload["body_md"]:
        raise RuntimeError("empty_body_from_model")
    payload["seed_keyword"] = seed[:200]
    payload["search_grounding_used"] = search_used
    payload["model_id"] = model_id
    payload["input_tokens"] = usage.get("input_tokens")
    payload["output_tokens"] = usage.get("output_tokens")
    return payload


_EN_FIELDS_SCHEMA = """
Respond with a single JSON object only (no markdown fence), keys:
- title_en (string, natural English, SEO-friendly, max 120 chars)
- excerpt_en (string, English, 1-2 sentences)
- meta_description_en (string, English, max 155 chars for Google snippet — no URLs)
- body_md_en (string, English body — {body_format_note})
"""


def _build_english_prompt(*, ko: dict[str, str], body_format: str, reference_notes: str) -> str:
    ref = (reference_notes or "").strip()
    ref_block = f"\n\n**Admin instructions (must respect):**\n{ref}\n" if ref else ""
    fmt = (body_format or "markdown").strip().lower()
    fmt_note = (
        "HTML preserving structure and image src URLs from the Korean body"
        if fmt == "html"
        else "Markdown with ## section headings only — no duplicate H1 at top"
    )
    return f"""You are an expert SAP technical writer and translator for "Catch Lab SAP Dev Hub".

**Task:** The Korean knowledge-base article below is complete. Write a natural English version for international practitioners and English search. Localize clearly while preserving meaning, structure, and technical accuracy.

**Korean article (source of truth):**
Title: {ko.get("title") or ""}
Excerpt: {ko.get("excerpt") or ""}
Meta: {ko.get("meta_description") or ""}
Body:
{ko.get("body_md") or ""}
{ref_block}
**Rules:**
- Match the Korean scope; do not add unrelated topics.
- Keep SAP terminology accurate.
- body_md_en: {fmt_note}
{_EN_FIELDS_SCHEMA.format(body_format_note=fmt_note)}
"""


def augment_kb_payload_with_english(
    payload: dict[str, Any],
    *,
    body_format: str = "markdown",
    reference_notes: str = "",
) -> dict[str, Any]:
    """한국어 초안 payload에 영문 필드를 추가(2차 Gemini 호출)."""
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    model_id = get_gemini_model_id()
    prompt = _build_english_prompt(
        ko={
            "title": payload.get("title") or "",
            "excerpt": payload.get("excerpt") or "",
            "meta_description": payload.get("meta_description") or "",
            "body_md": payload.get("body_md") or "",
        },
        body_format=body_format,
        reference_notes=reference_notes,
    )
    raw_text, usage = _call_gemini_plain(prompt=prompt, api_key=api_key, model_id=model_id)
    data = extract_json_object_from_llm_text(raw_text)
    if not data:
        raise RuntimeError("invalid_json_from_model_en")
    title_en = (str(data.get("title_en") or "")).strip()[:500]
    body_en = strip_leading_title_from_body_md(
        (str(data.get("body_md_en") or "")).strip(), title_en
    )
    if not body_en:
        raise RuntimeError("empty_body_en_from_model")
    payload["title_en"] = title_en
    payload["excerpt_en"] = (str(data.get("excerpt_en") or "")).strip()[:2000]
    payload["meta_description_en"] = sanitize_meta_description(
        (str(data.get("meta_description_en") or "")).strip(), max_len=320
    )
    payload["body_md_en"] = body_en
    payload["body_format_en"] = (body_format or "markdown").strip().lower()
    en_in = usage.get("input_tokens")
    en_out = usage.get("output_tokens")
    if en_in is not None:
        payload["input_tokens"] = (payload.get("input_tokens") or 0) + en_in
    if en_out is not None:
        payload["output_tokens"] = (payload.get("output_tokens") or 0) + en_out
    return payload


def finalize_kb_draft_payload(
    payload: dict[str, Any],
    *,
    also_english: bool,
    body_format: str = "markdown",
    reference_notes: str = "",
) -> dict[str, Any]:
    if also_english:
        augment_kb_payload_with_english(
            payload,
            body_format=body_format,
            reference_notes=reference_notes,
        )
    return payload
