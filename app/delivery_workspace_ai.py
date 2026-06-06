"""납품 작업실 — SE38 오류·슬롯 소스 기반 AI 수정 제안(컨설턴트 wallet 차감)."""

from __future__ import annotations

import re
from typing import Any

import google.generativeai as genai

from .ai_inquiry_guard import ai_inquiry_model_policy_footer
from .ai_usage_billing import ai_usage_context_for_delivery_job
from .ai_usage_recorder import ai_usage_scope, log_gemini_generate_content
from .delivery_workspace_fix_context import (
    _FS_MAX,
    build_full_package_abap_context,
)
from .delivery_workspace_se38_focus import build_se38_focus_section
from .gemini_model import get_gemini_model_id

STAGE_DELIVERY_WORKSPACE_FIX = "delivery_workspace_fix"

_ACTIVE_SLOT_OUTPUT_MAX = 48_000
_SE38_ERROR_MAX = 12_000

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
    fix_history_block: str = "",
    fs_text: str = "",
    package_guides_block: str = "",
    rag_kb_block: str = "",
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
    package_ctx, pkg_slot_count = build_full_package_abap_context(
        slots,
        active_index=int(active_slot_index),
        active_filename=slot_filename,
    )
    mains = [x.strip() for x in (main_slot_filenames or []) if (x or "").strip()]
    main_block = ", ".join(mains[:8]) if mains else "(패키지에 메인 슬롯 없음)"
    slot_kind = "INCLUDE/서브" if active_slot_is_include_like else "메인 또는 기타"
    fs_block = (fs_text or "").strip()
    if fs_block:
        fs_block = f"## 기능명세서(FS) — 요청·생성 맥락\n{fs_block[:_FS_MAX]}\n"
    guides_block = (package_guides_block or "").strip()
    rag_block = (rag_kb_block or "").strip()
    focus_block = build_se38_focus_section(err, src)
    history_block = (fix_history_block or "").strip()

    prompt = f"""당신은 SAP ABAP 납품 코드 수정 전문가입니다.
이 요청의 FS·제안서·인터뷰로 **개발코드가 생성된 뒤**, 컨설턴트가 SE38에서 본 오류를 해결합니다.

## UI 탭 선택의 의미 (중요)
- 컨설턴트가 선택한 탭 `{slot_filename}` 은 **SE38에서 오류가 표시된 위치(앵커)** 입니다.
- **이 탭 소스만 보라는 뜻이 아닙니다.** FS·아래 **패키지 ABAP 전체**를 읽고 원인·수정 위치를 판단하세요.
- 오류가 INCLUDE에서 보여도 수정은 메인·다른 INCLUDE일 수 있습니다.

{focus_block}
{history_block}
{fs_block}
{guides_block}

{rag_block}

{package_ctx}

## 판단
1. **FS·패키지 ABAP 전체·SE38 메시지**를 함께 보고 **실제로 고쳐야 할 파일·구문**을 찾으세요.
   (패키지 ABAP 슬롯 {pkg_slot_count}개 포함)
2. **[SE38 오류·징후]에 적힌 메시지·구문**만 1순위로 수정. 무관한 다른 행·다른 오류는 이번 응답에서 수정 금지.
3. 수정이 다른 파일에 있으면 → (B) 응답. 억지로 현재 탭만 syntax 맞추지 마세요.

## 응답 형식 (둘 중 하나만)

### A) 수정이 **현재 슬롯** `{slot_filename}` 에 있을 때만
- 수정된 ABAP **전체 소스**를 ```abap``` 블록으로 출력.
- SE38 오류가 가리키는 **최소 변경**만. INCLUDE·FORM 구조 유지.

### B) 수정이 **메인 또는 다른 슬롯**에 있을 때
- ```abap``` 블록에 **현재 슬롯 소스를 거의 그대로** 두고 최상단에만:
  * DW-FIX-ELSEWHERE: 수정 대상=<파일명> | 이유=<한 줄 한국어>

공통: 확실하지 않은 API 파라미터는 추측하지 말고 TODO. 설명 2문장 이내.

[SAP 버전 힌트] {ver}
[프로그램 ID] {prog}
[SE38 오류 보고 탭] {slot_filename} (role={slot_role}, {slot_kind})
[패키지 메인(REPORT) 파일명] {main_block}

[현재 슬롯 소스 — 수정 출력 대상 (SE38 오류 앵커)]
{src[:_ACTIVE_SLOT_OUTPUT_MAX]}

[SE38 오류·징후]
{err[:_SE38_ERROR_MAX]}

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
