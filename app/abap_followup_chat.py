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

from .agents.free_crew import SAP_KOREAN_CODE_ANALYSIS_STYLE
from .ai_inquiry_guard import ai_inquiry_model_policy_footer, check_ai_inquiry_user_text
from .gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 후속 채팅 코드 컨텍스트 (문자 수 = Python len. ABAP 한 줄에 대략 수십~백여 자 흔함)
# 13k 라인 합계는 보통 80만~120만 자 전후 → 전본 포함하려면 백만 자 이상 한도가 필요
_DEFAULT_FOLLOWUP_FULL_BELOW_CHARS = 1_500_000
_DEFAULT_FOLLOWUP_HARD_CAP_CHARS = 1_850_000
_DEFAULT_FOLLOWUP_TRIM_MAX_LINES = 12_000

MAX_USER_MESSAGE_CHARS = 4_000
MAX_USER_TURNS_PER_REQUEST = 60
MAX_ANALYSIS_JSON_CHARS = 14_000
MAX_HISTORY_MESSAGES = 24  # user+assistant pairs 최근 구간


def _followup_env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _collect_form_macro_names(question: str) -> set[str]:
    """PERFORM/FORM 이름."""
    q = question or ""
    names: set[str] = set()
    names.update(re.findall(r"(?is)\bPERFORM\s+(\w+)\b", q))
    names.update(re.findall(r"(?is)\bFORM\s+(\w+)\b", q))
    return {
        x
        for x in names
        if isinstance(x, str) and len(x) >= 3 and x.upper() not in {"TOP", "AND", "FOR", "END", "GET", "SET", "USING", "COMMIT"}
    }


def _extract_form_blocks(abap: str, names: set[str]) -> list[str]:
    """FORM … ENDFORM 블록(가능하면) 추출."""
    if not names or not abap:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for name in sorted(names):
        if name.upper() == "TABLES":
            continue
        escaped = re.escape(name)
        # ABAP FORM name can include hyphens rarely; 우선 알파토큼
        m = re.search(
            rf"(?ims)^([\s*&]*FORM\s+{escaped}\s*(?:\.)?(?:[^\n]*?\n).*?^[ \t]*ENDFORM\b\.?$)",
            abap,
        )
        if m and name not in seen:
            block = (m.group(1) or "").strip()
            if len(block) > 40:
                out.append(f"* --- FORM {name} (질문·키워드로 추출) ---\n{block}")
                seen.add(name)
    return out[:10]


def _line_is_data_related(abap_line: str) -> bool:
    """Z/Y·내부테이블·JOIN·SELECT 등 데이터 접근으로 보이는 줄."""
    u = abap_line.rstrip()
    if not u.strip():
        return False
    if re.search(
        r"(?i)(\b(gt_|it_|zt_|zc_|zr|zl|yv|wk_)[a-z0-9_]*)|\bZ[A-Z0-9_]{3,}\b|\bz[a-z0-9_]{3,}\b",
        u,
    ) and re.search(
        r"(?i)\b(SELECT|SINGLE(\s+FROM)?|BY\s+PASSING)\b|\bFROM\b|\bJOIN\b|\bINTO\s+(TABLE|SINGLE)|"
        r"\bFOR\s+ALL\s+ENTRIES\b|\bWHERE\b|\bINNER\s+JOIN\b|\bLEFT\s+OUTER\s+JOIN\b",
        u,
    ):
        return True
    return False


def _extract_sql_join_lines(abap: str, question_lower: str) -> list[str]:
    """테이블/조인/SELECT 성격 질문이면, 데이터 접근 줄을 소스 전체에서 수집."""
    if not abap:
        return []
    trig = (
        "테이블",
        "조인",
        "join",
        "select",
        "from ",
        "z",
        "field",
        "필드",
        "컬럼",
        "키",
        "연결",
    )
    q = (question_lower or "").strip()
    if not any(k in q for k in trig):
        return []
    lines = abap.splitlines()
    hit: list[str] = []
    for ln in lines:
        s = ln.rstrip()
        if len(s) > 400:
            s = s[:400] + "…"
        if _line_is_data_related(s):
            hit.append(s)
        if len(hit) >= 400:
            break
    return hit


def _build_followup_code_excerpt(source_code: str, user_question: str) -> tuple[str, str]:
    """
    후속 질문용 ABAP 컨텍스트.

    반환:
      (코드 문자열, 모델·회원에게 설명할 문구)

    한도 이하는 **전본** 포함. 초과 시 슬롯 균형 트림 후, 질문 키워드로 폼 블록·SQL 관련 줄을 보충한다.
    """
    raw = source_code or ""
    src = raw.strip()
    if not src:
        return "", ""

    full_below = _followup_env_int("ABAP_FOLLOWUP_FULL_BELOW_CHARS", _DEFAULT_FOLLOWUP_FULL_BELOW_CHARS)
    hard_cap = _followup_env_int("ABAP_FOLLOWUP_CODE_HARD_CAP_CHARS", _DEFAULT_FOLLOWUP_HARD_CAP_CHARS)
    trim_ml = _followup_env_int("ABAP_FOLLOWUP_TRIM_MAX_LINES", _DEFAULT_FOLLOWUP_TRIM_MAX_LINES)

    # 짧은 제출: 전본만 넣고 끝(보충으로 중복·토큰만 늘지 않게)
    if len(raw) <= full_below:
        note = "아래 「ABAP 원문」에는 **회원이 제출한 코드 전본**을 넣었다."
        combined = raw
        if len(combined) > hard_cap:
            combined = (
                combined[:hard_cap].rstrip()
                + "\n\n… [시스템] 후속 질문용 코드 컨텍스트가 길이 상한("
                + f"{hard_cap:,}"
                + "자)에 걸려 잘렸다. …"
            )
            note += " (전본이 길어 상한으로 잘림)"
        return combined, note

    q_low = (user_question or "").lower()
    names = _collect_form_macro_names(user_question or "")

    from .agents.free_crew import trim_code_for_abap_analysis

    base = trim_code_for_abap_analysis(src, max_lines=trim_ml)
    note_parts: list[str] = [
        "제출 코드가 매우 길어 헤더·키워드 기반 요약 후 본이다. 질문에 폼·테이블 키워드가 있으면 아래에 보충했다."
    ]

    forms = _extract_form_blocks(src, names)
    sql_ln = _extract_sql_join_lines(src, q_low)
    supplemental: list[str] = []
    if forms:
        supplemental.extend(forms)
        note_parts.append("질문에 나온 FORM/PERFORM 이름과 맞으면 해당 FORM … ENDFORM 전체를 별도로 첨부했다.")
    if sql_ln:
        block = "* --- FROM/JOIN/WHERE 등이 포함된 줄(전체 소스에서 수집) ---\n" + "\n".join(sql_ln)
        supplemental.append(block)
        note_parts.append("테이블·조인·SELECT 관련 줄을 소스 전체에서 뽑아 추가했다.")

    combined = base
    if supplemental:
        combined = base.rstrip() + "\n\n" + "\n\n".join(supplemental)
    if len(combined) > hard_cap:
        combined = combined[:hard_cap].rstrip() + (
            "\n\n… [시스템] 후속 질문용 코드 컨텍스트가 길이 상한("
            f"{hard_cap:,}자"
            ")에 걸려 잘렸다. 같은 질문을 더 좁히거나 프로그램·폼 이름을 명시하면 좋다. …"
        )
        note_parts.append("내용이 길이 상한으로 잘린 구간이 있을 수 있다.")

    note = " ".join(note_parts)
    return combined, note


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
    code_excerpt, code_note = _build_followup_code_excerpt(source_code or "", user_question.strip())
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

    prompt = f"""당신은 SAP ABAP 선임 컨설턴트다. 아래 **제출된 요구사항**, **ABAP 소스 원문 또는 서버가 구성한 컨텍스트**, **이미 생성된 분석 JSON**, **지금까지의 후속 대화**를 바탕으로
회원의 **새 질문**에만 답한다.

{SAP_KOREAN_CODE_ANALYSIS_STYLE}

[후속 분석 코드 컨텍스트 — 서버가 구성함]
{code_note}

규칙:
- 소스에 없는 기능을 사실처럼 단정하지 마라. 추정이면 추정임을 분명히 한다.
- **아래 코드 블록에 실린 내용**(전본이거나, 길 경우 요약+선택 줄·폼 보충)을 **먼저** 근거로 삼아 Z테이블·SELECT·JOIN·키 필드를 특정한다. 컨텍스트에 명시 안 된 줄은 「제공된 소스에서는 안 보임」이라고 한다.
- **첨부 요약 블록**이 있으면, 회원 질문이 파일·시트에 관한 것이라면 그 내용을 근거로 답한다. 파일을 「직접 열어볼」 수 있는 것처럼 말하지 말고, **서버가 아래에 넣어 준 요약**을 전제로 설명한다.
- 답변 안에서 회원에게 붙여 보여 줄 **소스 재인용**은 장황하게 중복 출력하지 마라 (질문에 답하는 데 필요한 최소 인용 위주).
- 마크다운 소제목(##)은 쓰지 않아도 된다. 가독성 있게 짧은 문단·불릿 위주.
- 회원이 한국어로 물었으면 한국어로 답한다.

[회원 요구사항(제출)]
{req}

[분석 결과 JSON — 서버가 이미 생성한 구조·요구 연계 분석]
{aj}

[ABAP 원문 또는 서버 추출 코드 컨텍스트]
```abap
{code_excerpt}
```
{att_block}
[지금까지의 후속 대화]
{hist_text}

[회원의 새 질문]
{user_question.strip()}

위 새 질문에 대해서만 답변 본문을 작성하라. 인사말 생략."""
    prompt = prompt + ai_inquiry_model_policy_footer()

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
    blocked = check_ai_inquiry_user_text(s)
    if blocked:
        return None, blocked
    return s, None
