"""
ABAP 분석 상세 페이지 — 동일 제출 코드·분석 결과를 맥락으로 후속 질문에 답합니다.
Gemini 직접 호출(경량). CrewAI 미사용.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from .agents.free_crew import SAP_KOREAN_CODE_ANALYSIS_STYLE, trim_code_for_abap_analysis
from .gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_USER_MESSAGE_CHARS = 4_000
MAX_USER_TURNS_PER_REQUEST = 60
MAX_ANALYSIS_JSON_CHARS = 14_000
MAX_HISTORY_MESSAGES = 24  # user+assistant pairs 최근 구간


def _get_model() -> genai.GenerativeModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_gemini_model_id())


def _format_history(rows: list) -> str:
    lines: list[str] = []
    for m in rows:
        role = (m.role or "").strip().lower()
        label = "회원" if role == "user" else "어시스턴트"
        text = (m.content or "").strip()
        if not text:
            continue
        lines.append(f"[{label}]\n{text}")
    return "\n\n".join(lines) if lines else "(아직 후속 대화 없음)"


def generate_followup_reply(
    *,
    requirement_text: str,
    source_code: str,
    analysis_obj: dict,
    history_messages: list,
    user_question: str,
    attachment_digest: str = "",
) -> str:
    """분석 맥락 + 대화 이력 + 새 질문에 대한 한국어 답변(일반 텍스트)."""
    req = (requirement_text or "").strip()[:20_000]
    code_excerpt = trim_code_for_abap_analysis(source_code or "", max_lines=320)
    try:
        aj = json.dumps(analysis_obj, ensure_ascii=False)
    except Exception:
        aj = str(analysis_obj)
    if len(aj) > MAX_ANALYSIS_JSON_CHARS:
        aj = aj[: MAX_ANALYSIS_JSON_CHARS] + "\n…(이하 생략)…"

    att = (attachment_digest or "").strip()
    att_block = ""
    if att:
        att_block = f"\n\n[첨부·참고 자료 — 서버에서 추출한 텍스트 요약]\n{att[:24_000]}\n"

    hist = history_messages[-MAX_HISTORY_MESSAGES:] if history_messages else []
    hist_text = _format_history(hist)

    prompt = f"""당신은 SAP ABAP 선임 컨설턴트다. 아래 **제출된 요구사항**, **ABAP 소스 일부**, **이미 생성된 분석 JSON**, **지금까지의 후속 대화**를 바탕으로
회원의 **새 질문**에만 답한다.

{SAP_KOREAN_CODE_ANALYSIS_STYLE}

규칙:
- 소스에 없는 기능을 사실처럼 단정하지 마라. 추정이면 추정임을 분명히 한다.
- **첨부 요약 블록**이 있으면, 회원 질문이 파일·시트에 관한 것이라면 그 내용을 근거로 답한다. 파일을 「직접 열어볼」 수 있는 것처럼 말하지 말고, **서버가 아래에 넣어 준 요약**을 전제로 설명한다.
- 코드 인용은 필요한 만큼만 짧게. 전체 프로그램을 다시 붙이지 마라.
- 마크다운 소제목(##)은 쓰지 않아도 된다. 가독성 있게 짧은 문단·불릿 위주.
- 회원이 한국어로 물었으면 한국어로 답한다.

[회원 요구사항(제출)]
{req}

[분석 결과 JSON — 서버가 이미 생성한 구조·요구 연계 분석]
{aj}

[ABAP 소스 일부(토큰 절약을 위해 잘림)]
```abap
{code_excerpt}
```
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


def validate_user_message(text: str) -> tuple[str | None, str | None]:
    """(정제된 메시지, 에러 한글) — 성공 시 (msg, None)."""
    s = (text or "").strip()
    if not s:
        return None, "질문 내용을 입력해 주세요."
    if len(s) > MAX_USER_MESSAGE_CHARS:
        return None, f"질문은 {MAX_USER_MESSAGE_CHARS:,}자 이하로 입력해 주세요."
    if not re.search(r"\S", s):
        return None, "질문 내용을 입력해 주세요."
    return s, None
