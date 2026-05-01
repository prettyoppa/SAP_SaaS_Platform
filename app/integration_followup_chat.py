"""연동 개발 상세 — 후속 질문 응답 (Gemini 직접 호출)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from .gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_USER_MESSAGE_CHARS = 4_000
MAX_HISTORY_MESSAGES = 24


def _get_model():
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
    return genai.GenerativeModel(get_gemini_model_id())


def _format_history(rows: list) -> str:
    lines: list[str] = []
    for m in rows:
        role = (getattr(m, "role", None) or "").strip().lower()
        label = "회원" if role == "user" else "어시스턴트"
        text = (getattr(m, "content", None) or "").strip()
        if not text:
            continue
        lines.append(f"[{label}]\n{text}")
    return "\n\n".join(lines) if lines else "(아직 후속 대화 없음)"


def generate_integration_followup_reply(
    *,
    ir_summary: str,
    history_messages: list,
    user_question: str,
    attachment_digest: str = "",
) -> str:
    hist = history_messages[-MAX_HISTORY_MESSAGES:] if history_messages else []
    hist_text = _format_history(hist)
    att = (attachment_digest or "").strip()
    att_block = ""
    if att:
        att_block = f"\n\n[첨부·참고 자료 요약]\n{att[:24_000]}\n"

    prompt = f"""당신은 SAP 연동·비ABAP 자동화(VBA, Python, 배치, API 등) 시니어 컨설턴트다.
아래 **연동 요청 요약**, **지금까지의 후속 대화**, **첨부 요약(있을 때)**을 바탕으로 회원의 새 질문에만 답한다.

규칙:
- SAP RFC/OData/배치·보안·운영 환경 질문에는 일반적인 모범 관점으로 답하되, 확인되지 않은 고객 시스템 사실은 단정하지 않는다.
- 회원이 한국어로 물었으면 한국어로 답한다.
- 마크다운 소제목(##)은 필수 아님. 짧은 문단·불릿 위주.

[연동 요청 요약]
{ir_summary[:40_000]}
{att_block}
[지금까지의 후속 대화]
{hist_text}

[회원의 새 질문]
{user_question.strip()}

위 새 질문에 대해서만 답변 본문을 작성하라. 인사말 생략."""

    model = _get_model()
    response = model.generate_content(prompt)
    try:
        raw = (response.text or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return "응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
    return raw


def validate_integration_user_message(text: str) -> tuple[str | None, str | None]:
    s = (text or "").strip()
    if not s:
        return None, "질문 내용을 입력해 주세요."
    if len(s) > MAX_USER_MESSAGE_CHARS:
        return None, f"질문은 {MAX_USER_MESSAGE_CHARS:,}자 이하로 입력해 주세요."
    if not re.search(r"\S", s):
        return None, "질문 내용을 입력해 주세요."
    return s, None


def integration_request_llm_summary(ir) -> str:
    """프롬프트용 요약 문자열."""
    parts = [
        f"제목: {getattr(ir, 'title', '') or ''}",
        f"구현 형태: {getattr(ir, 'impl_types', '') or ''}",
        f"SAP 터치포인트:\n{getattr(ir, 'sap_touchpoints', '') or '—'}",
        f"실행 환경:\n{getattr(ir, 'environment_notes', '') or '—'}",
        f"보안·권한:\n{getattr(ir, 'security_notes', '') or '—'}",
        f"상세 설명:\n{getattr(ir, 'description', '') or '—'}",
    ]
    return "\n\n".join(parts)
