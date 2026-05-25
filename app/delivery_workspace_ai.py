"""납품 작업실 — SE38 오류·슬롯 소스 기반 AI 수정 제안(컨설턴트 wallet 차감)."""

from __future__ import annotations

import re
from typing import Any

import google.generativeai as genai

from .ai_inquiry_guard import ai_inquiry_model_policy_footer
from .ai_usage_billing import ai_usage_context_for_delivery_job
from .ai_usage_recorder import ai_usage_scope, log_gemini_generate_content
from .gemini_model import get_gemini_model_id

STAGE_DELIVERY_WORKSPACE_FIX = "delivery_workspace_fix"

_FENCE_RE = re.compile(
    r"```(?:abap|ABAP)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _get_model():
    import os

    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if api_key:
        genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_gemini_model_id())


def extract_suggested_abap(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def suggest_slot_fix(
    *,
    billing_user_id: int,
    request_kind: str,
    request_id: int,
    slot_filename: str,
    slot_role: str,
    current_source: str,
    se38_error: str,
    sap_version_hint: str = "",
    program_id: str = "",
) -> tuple[str, str | None]:
    """
    Returns (suggested_abap, error_code).
    error_code: wallet_insufficient | ai_failed | empty
    """
    err = (se38_error or "").strip()
    if not err:
        return "", "missing_error"
    src = (current_source or "").strip()
    if not src:
        return "", "missing_source"

    ctx = ai_usage_context_for_delivery_job(
        billing_user_id=int(billing_user_id),
        request_kind=request_kind,
        request_id=int(request_id),
    )
    ver = (sap_version_hint or "").strip() or "미지정"
    prog = (program_id or "").strip() or "미지정"

    prompt = f"""당신은 SAP ABAP 납품 코드 수정 전문가입니다.
컨설턴트가 SE38에서 실행·활성화하다 본 오류를 해결하도록, **해당 슬롯 ABAP 소스만** 수정한 전체 소스를 제안하세요.

규칙:
- 출력은 수정된 ABAP 소스만. 설명·인사는 최소화(2문장 이내 가능).
- 가능하면 ```abap 코드블록``` 하나로 감싸세요.
- INCLUDE·FORM·클래스 구조는 유지하고 오류 원인만 최소 수정.
- 확실하지 않은 고객 커스텀 테이블/함수는 추측하지 말고 주석으로 TODO 표시.

[SAP 버전 힌트] {ver}
[프로그램 ID] {prog}
[슬롯 파일] {slot_filename}
[슬롯 역할] {slot_role}

[현재 슬롯 소스]
{src[:48_000]}

[SE38 오류·징후]
{err[:8_000]}

위 오류를 해소하는 수정 ABAP 전체를 제안하세요."""
    prompt = prompt + ai_inquiry_model_policy_footer()

    try:
        with ai_usage_scope(ctx):
            response = _get_model().generate_content(prompt)
            log_gemini_generate_content(
                response,
                stage=STAGE_DELIVERY_WORKSPACE_FIX,
                user_id=int(billing_user_id),
                request_kind=request_kind,
                request_id=request_id,
            )
            raw = (response.text or "").strip()
    except Exception:
        return "", "ai_failed"

    suggested = extract_suggested_abap(raw)
    if not suggested:
        return "", "empty"
    return suggested, None
