"""신규 개발(RFP) 통합 허브 — 회원 질문·AI 응답 (Gemini)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .ai_inquiry_guard import ai_inquiry_model_policy_footer
from .attachment_context import build_attachment_llm_digest
from .gemini_model import get_gemini_model_id
from .abap_followup_chat import MAX_USER_TURNS_PER_REQUEST
from .integration_followup_chat import validate_integration_user_message
from .routers.interview_router import _conversation_list_for_llm

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_HISTORY_MESSAGES = 24


def pair_followup_turn_messages(msgs: list) -> list[dict]:
    """user → assistant 순을 한 턴으로 묶어 상세 화면 접이식 UI에 사용."""
    out: list[dict] = []
    i = 0
    n = len(msgs)
    while i < n:
        m = msgs[i]
        role = (getattr(m, "role", None) or "").strip().lower()
        if role == "user":
            q = m
            a = None
            if i + 1 < n and (getattr(msgs[i + 1], "role", None) or "").strip().lower() == "assistant":
                a = msgs[i + 1]
                i += 2
            else:
                i += 1
            out.append({"question": q, "answer": a})
        elif role == "assistant":
            out.append({"question": None, "answer": m})
            i += 1
        else:
            i += 1
    return out


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
    return "\n\n".join(lines) if lines else "(아직 이 채널에서 나눈 대화 없음)"


def _interview_digest_for_prompt(rfp) -> str:
    conv = _conversation_list_for_llm(rfp)
    if not conv:
        return ""
    lines: list[str] = []
    for row in conv[-10:]:
        rnd = row.get("round_number")
        qs = row.get("questions") or []
        ans = (row.get("answers_text") or "").strip()
        lines.append(f"— 라운드 {rnd} —")
        for q in qs[:6]:
            if isinstance(q, str):
                qtxt = q.strip()
            else:
                qtxt = json.dumps(q, ensure_ascii=False)[:600]
            if qtxt:
                lines.append(f"질문: {qtxt}")
        if ans:
            lines.append(f"답변 요약:\n{ans[:3500]}")
        lines.append("")
    return "\n".join(lines).strip()[:14_000]


def rfp_followup_context_block(
    *,
    db: Session,
    rfp,
    attachment_entries: list[dict[str, Any]],
) -> str:
    """단일 프롬프트 블록: 요청 카드 + 인터뷰 요약 + 제안서 일부 + 첨부 요약."""
    parts: list[str] = []
    parts.append("[요청 요약]")
    parts.append(f"제목: {(rfp.title or '').strip()}")
    parts.append(f"프로그램 ID: {(rfp.program_id or '').strip() or '—'}")
    parts.append(f"T-code: {(rfp.transaction_code or '').strip() or '—'}")
    parts.append(f"SAP 모듈(코드): {(rfp.sap_modules or '').strip() or '—'}")
    parts.append(f"개발 유형(코드): {(rfp.dev_types or '').strip() or '—'}")
    wo = (getattr(rfp, "workflow_origin", None) or "direct").strip()
    parts.append(f"워크플로 출처: {wo or 'direct'}")
    parts.append(f"요구사항 본문:\n{(rfp.description or '').strip() or '—'}")

    iv = _interview_digest_for_prompt(rfp)
    if iv:
        parts.append("")
        parts.append("[인터뷰 진행 요약]")
        parts.append(iv)

    prop = (getattr(rfp, "proposal_text", None) or "").strip()
    if prop:
        parts.append("")
        parts.append("[제안서 초안 일부]")
        parts.append(prop[:10_000])

    fs_st = (getattr(rfp, "fs_status", None) or "").strip()
    if fs_st and fs_st != "none":
        parts.append("")
        parts.append(f"[FS 상태] {fs_st}")

    att = build_attachment_llm_digest(attachment_entries or [], max_total_chars=9000)
    if att.strip():
        parts.append("")
        parts.append("[첨부·메모 요약]")
        parts.append(att[:24_000])

    return "\n\n".join(parts)[:42_000]


def generate_rfp_followup_reply(
    *,
    context_block: str,
    history_messages: list,
    user_question: str,
    owner_user_id: int | None = None,
    request_id: int | None = None,
) -> str:
    hist = history_messages[-MAX_HISTORY_MESSAGES:] if history_messages else []
    hist_text = _format_history(hist)

    prompt = f"""당신은 SAP ABAP 신규 개발·기능명세·납품 단계를 아는 시니어 컨설턴트다.
아래 **요청·인터뷰·제안서 맥락**과 **지금까지 이 채널의 대화**를 바탕으로, 회원의 새 질문에만 답한다.

규칙:
- IT 전문가가 아닌 사용자도 이해하도록, 짧은 문장과 필요 시 불릿으로 설명한다.
- 확실하지 않은 고객 시스템 사실은 단정하지 않고, 확인하거나 제안서·FS 단계에서 다룰 수 있다고 안내한다.
- 한국어 질문에는 한국어로 답한다.
- 마크다운 소제목(##)은 필수 아님.

[요청·인터뷰·제안 맥락]
{context_block[:40_000]}

[이 채널에서 지금까지의 대화]
{hist_text}

[회원의 새 질문]
{user_question.strip()}

위 새 질문에 대해서만 답변 본문을 작성하라. 인사말 생략."""
    prompt = prompt + ai_inquiry_model_policy_footer()

    model = _get_model()
    response = model.generate_content(prompt)
    if owner_user_id:
        from .ai_usage_recorder import log_gemini_generate_content

        log_gemini_generate_content(
            response,
            stage="ai_inquiry",
            user_id=int(owner_user_id),
            request_kind="rfp",
            request_id=request_id,
        )
    try:
        raw = (response.text or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return "응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
    return raw


def validate_rfp_user_message(text: str) -> tuple[str | None, str | None]:
    return validate_integration_user_message(text)


__all__ = [
    "MAX_USER_TURNS_PER_REQUEST",
    "generate_rfp_followup_reply",
    "pair_followup_turn_messages",
    "rfp_followup_context_block",
    "validate_rfp_user_message",
]
