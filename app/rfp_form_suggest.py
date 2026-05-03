"""
RFP 신규/수정 폼 — AI 자동 생성(요약 제목, Z 프로그램 ID).
요구사항 자유 기술이 일정 길이 미만이면 호출하지 않는다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from .gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# AI 제안·임시저장 필수 검증 공통: 너무 짧으면 맥락 부족으로 간주
MIN_RFP_DESCRIPTION_CHARS = 40

_PRINTABLE_ASCII = re.compile(r"^[!-~]+$")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")


def description_sufficient_for_suggest(text: str | None) -> bool:
    return len((text or "").strip()) >= MIN_RFP_DESCRIPTION_CHARS


def _configure_genai() -> genai.GenerativeModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_gemini_model_id())


def _strip_model_noise(s: str) -> str:
    t = (s or "").strip()
    t = t.strip('"').strip("'").strip()
    for prefix in ("제목:", "요청제목:", "Title:", "title:"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix) :].strip()
    return t


def suggest_title_from_description(description: str) -> str:
    """요구사항 본문 → 요청 제목 한 줄. 원문이 영어면 영어로, 한국어면 한국어로 요약(최대 50자·문자 기준)."""
    body = (description or "").strip()[:12000]
    model = _configure_genai()
    prompt = f"""다음은 SAP 맞춤개발 의뢰의 「요구사항 자유 기술」 원문이다.

**언어:** 원문이 주로 **영어**로 쓰여 있으면 **영어**로, 주로 **한국어**면 **한국어**로, 혼합이면 **가장 많이 쓰인 언어**로 요청 제목을 써라. (번역하지 말고 그 언어로만.)

**출력:** 요청 제목 **한 줄만**. 조건:
- 업무 맥락이 드러나도록 간결하게
- **50자(문자) 이하** — 영어면 단어 수보다 글자 수 기준
- 따옴표·머리말·번호·불릿 없이 본문만

[요구사항]
{body}
"""
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=256,
            temperature=0.35,
        ),
    )
    text = _strip_model_noise(getattr(resp, "text", "") or "")
    if not text:
        raise RuntimeError("empty_model_output")
    # 문자 기준 50자
    if len(text) > 50:
        text = text[:50].rstrip()
    return text


def _normalize_program_token(raw: str) -> str:
    s = (raw or "").strip().upper()
    s = re.sub(r"[^A-Z0-9_]", "", s)
    if not s.startswith("Z"):
        s = "Z" + s
    s = s[:40]
    if _CJK_RE.search(s) or not _PRINTABLE_ASCII.match(s):
        return ""
    return s


def suggest_program_id_from_title(title: str) -> str:
    """요청 제목 → Z로 시작하는 ABAP 프로그램명 후보(영문·숫자·밑줄, 길이 제한)."""
    t = (title or "").strip()[:500]
    if not t:
        raise ValueError("empty_title")
    model = _configure_genai()
    prompt = f"""다음은 요청 제목이다(한국어·영어 등 어떤 언어든 될 수 있다). SAP ABAP **프로그램 이름** 하나로 바꿔라.

규칙:
- 반드시 **Z** 로 시작 (맨 앞 한 글자)
- **영문 대문자, 숫자, 밑줄(_)** 만 사용. 공백·하이픈·한글 금지.
- 의미를 담은 짧은 약어 조합 (예: ZSD_SO_LIST)
- 길이 **30자 이하** (Z 포함)
- 설명·따옴표·부연 없이 **식별자 한 덩어리만** 출력

[요청 제목]
{t}
"""
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=128,
            temperature=0.25,
        ),
    )
    raw = _strip_model_noise(getattr(resp, "text", "") or "")
    if not raw:
        raise RuntimeError("empty_model_output")
    token = _normalize_program_token(raw.split()[0] if raw else "")
    if not token:
        # 폴백: ZREQ + 해시 대신 간단 접두
        base = re.sub(r"[^A-Z0-9]", "", t.upper())[:12] or "REQ"
        token = _normalize_program_id_fallback(base)
    return token[:40]


def _normalize_program_id_fallback(ascii_fragment: str) -> str:
    frag = re.sub(r"[^A-Z0-9]", "", (ascii_fragment or "").upper())[:20]
    if not frag:
        frag = "CUSTOM"
    s = "Z" + frag
    return s[:40]
