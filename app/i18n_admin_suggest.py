"""관리자 UI 문자열 → 영어 번역 제안 (Gemini)."""

from __future__ import annotations

import os
import re

import google.generativeai as genai

from .gemini_model import get_gemini_model_id

_APP_INTRO = """You are helping translate UI strings for "SAP Dev Hub" (Catchy Lab): a web app where members submit SAP ABAP development requests (RFPs), run AI-guided interviews, receive development proposals, and optionally engage paid delivery. There are also integration requests, ABAP code analysis, a code gallery, subscriptions, and account pages. Tone: concise, professional SaaS English; keep SAP terms where natural; preserve HTML tags if present."""

_MAX_OUT = 2048


def _model() -> genai.GenerativeModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_gemini_model_id())


def suggest_ui_english(
    *,
    i18n_key: str,
    korean_ui: str,
    english_current: str,
    screen_title_ko: str,
    screen_purpose_ko: str,
) -> str:
    ko = (korean_ui or "").strip()
    if not ko:
        raise ValueError("empty_korean")
    cur = (english_current or "").strip()
    screen = (screen_title_ko or "").strip()
    purpose = (screen_purpose_ko or "").strip()
    model = _model()
    prompt = f"""{_APP_INTRO}

**Screen (Korean label for admins):** {screen}
**Screen purpose (Korean):** {purpose}

**i18n key:** `{i18n_key}`

**Korean UI string to translate:**
{ko}

**Existing English in codebase (may be empty — improve if needed, do not invent unrelated product claims):**
{cur if cur else "(none)"}

**Output rules:**
- Return **only** the English string that should appear in the EN locale for this UI slot.
- Match register: button labels short; sentences may be slightly longer.
- Preserve any HTML tags (`<strong>`, `&amp;`, etc.) exactly as structure needs; fix only language.
- No quotes around the answer; no "Translation:" prefix; single line unless the Korean clearly needs a line break (rare).
"""
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=_MAX_OUT,
            temperature=0.25,
        ),
    )
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty_model_output")
    text = re.sub(r"^[\"']|[\"']$", "", text.strip())
    return text
