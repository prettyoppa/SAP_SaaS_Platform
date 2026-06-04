"""납품 작업실 — SE38 오류·슬롯 소스 기반 AI 수정 제안(컨설턴트 wallet 차감)."""

from __future__ import annotations

import re
from typing import Any

import google.generativeai as genai

from .ai_inquiry_guard import ai_inquiry_model_policy_footer
from .ai_usage_billing import ai_usage_context_for_delivery_job
from .ai_usage_recorder import ai_usage_scope, log_gemini_generate_content
from .delivery_workspace_context import build_peer_sources_context
from .delivery_workspace_se38_focus import build_se38_focus_section
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
    package_slots: list[dict] | None = None,
    active_slot_index: int = 0,
    main_slot_filenames: list[str] | None = None,
    active_slot_is_include_like: bool = False,
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
    slots = [s for s in (package_slots or []) if isinstance(s, dict)]
    peer_ctx, peer_count = build_peer_sources_context(
        slots, active_index=int(active_slot_index)
    )
    mains = [x.strip() for x in (main_slot_filenames or []) if (x or "").strip()]
    main_block = ", ".join(mains[:8]) if mains else "(패키지에 메인 슬롯 없음)"
    slot_kind = "INCLUDE/서브" if active_slot_is_include_like else "메인 또는 기타"
    peer_note = (
        f"이번 요청에 다른 ABAP 탭 소스 {peer_count}개가 **읽기 전용**으로 포함되어 있습니다."
        if peer_count
        else "다른 ABAP 탭 소스는 비어 있거나 포함되지 않았습니다."
    )

    focus_block = build_se38_focus_section(err, src)

    prompt = f"""당신은 SAP ABAP 납품 코드 수정 전문가입니다.
컨설턴트가 SE38에서 본 오류를 해결하려 합니다. **오류가 현재 파일에서 보고되었어도, 원인·수정 위치는 메인(REPORT) 또는 다른 INCLUDE일 수 있습니다.**

{focus_block}
## 판단 (가장 중요)
1. **[패키지 다른 슬롯 소스]**와 **[현재 슬롯 소스]**·SE38 메시지를 함께 보고 **실제로 고쳐야 할 파일**을 판단하세요. ({peer_note})
2. 예: INCLUDE A에서 syntax error가 났지만, **[패키지 다른 슬롯]**의 메인에 INCLUDE 문·선언 오류가 보이면 **INCLUDE A를 억지로 고치지 마세요.**
3. 수정이 다른 파일에 있으면 → 아래 (B) 응답. 그 파일의 소스 내용을 참고해 **어느 파일인지** 주석에 정확히 적으세요.

## 응답 형식 (둘 중 하나만)

### A) 수정이 **현재 슬롯**에 있을 때만
- 수정된 ABAP **전체 소스**를 ```abap``` 블록으로 출력 (diff 표시용 — 화면에 전체를 다시 보여주지 않음).
- **[SE38 오류·징후]와 컨설턴트가 붙인 구문**이 가리키는 위치만 **최소 변경**. 무관한 다른 행은 원문 그대로.
- INCLUDE·FORM 구조 유지. 소스 길이를 임의로 대폭 줄이지 마세요.

### B) 수정이 **메인 또는 다른 슬롯**에 있을 때 (현재 슬롯을 억지로 고치지 말 것)
- ```abap``` 블록 안에 **현재 슬롯 소스를 거의 그대로** 두고, 최상단에만 아래 주석 1~3줄 추가:
  * DW-FIX-ELSEWHERE: 수정 대상=<파일명> | 이유=<한 줄 한국어>
- 그 외 본문을 syntax 맞추려고 임의 변경·삭제·우회 코드를 넣지 마세요.

공통:
- 확실하지 않은 커스텀 객체는 추측하지 말고 TODO 주석.
- 설명 문단은 2문장 이내로 짧게 가능.

[SAP 버전 힌트] {ver}
[프로그램 ID] {prog}
[현재 슬롯 파일] {slot_filename}
[현재 슬롯 역할] {slot_role} ({slot_kind})
[패키지 메인(REPORT) 파일명] {main_block}

[패키지 다른 슬롯 소스 — 읽기 전용, 출력은 현재 슬롯만]
{peer_ctx[:32_000]}

[현재 슬롯 소스 — 여기만 수정 출력 가능]
{src[:24_000]}

[SE38 오류·징후]
{err[:8_000]}

위 오류에 대해 (A) 또는 (B)로 응답하세요."""
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
