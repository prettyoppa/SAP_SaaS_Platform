"""
Free Tier Crew – SAP Dev Hub

에이전트 구성:
  f_questioner  (Mia)   – 전 라운드 인터뷰 질문 생성 전담
  f_analyst     (Hannah)– 전 라운드 답변 분석 전담
  f_writer      (Jun)   – Development Proposal 작성
  f_reviewer    (Sara)  – Proposal 품질 검토 및 최종 승인

플로우:
  [라운드 질문 생성] f_analyst → f_questioner (라운드마다 호출)
  [Proposal 생성]   f_analyst → f_writer → f_reviewer (인터뷰 완료 후 1회 호출)
"""

import json
import os
import re
from pathlib import Path

from crewai import Agent, Task, Crew, Process, LLM
from dotenv import load_dotenv

from ..gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MAX_ROUNDS = 3


def _parse_code_library_context(code_library_context: str) -> tuple[str, dict]:
    """JSON code_library_context → (analysis_summary, 전체 dict)."""
    if not code_library_context or not str(code_library_context).strip():
        return "", {}
    try:
        ctx = json.loads(code_library_context)
        if not isinstance(ctx, dict):
            return "", {}
        summary = (ctx.get("analysis_summary") or "").strip()
        return summary, ctx
    except Exception:
        return "", {}


def _format_library_block_for_mia(code_library_context: str) -> str:
    """Mia 태스크용: 질문 목록 + 요약 (원시 JSON 대신 가독 형식)."""
    summary, ctx = _parse_code_library_context(code_library_context)
    qs = ctx.get("questions") if ctx else None
    chunks = []
    if qs and isinstance(qs, list):
        lines = [f"- {q}" for q in qs[:6] if q]
        if lines:
            chunks.append("역추출 인터뷰 질문 후보:\n" + "\n".join(lines))
    if summary:
        chunks.append("유사 프로그램 요약:\n" + summary[:3200])
    return "\n\n".join(chunks) if chunks else "없음"


# ── SAP 레이블 맵 ─────────────────────────────────────

_MODULE_LABELS = {
    "SD": "Sales & Distribution (영업/유통)",
    "MM": "Materials Management (자재 관리)",
    "FI": "Financial Accounting (재무 회계)",
    "CO": "Controlling (관리 회계)",
    "PP": "Production Planning (생산 계획)",
    "QM": "Quality Management (품질 관리)",
    "PM": "Plant Maintenance (설비 관리)",
    "HCM": "Human Capital Management (인사 관리)",
    "WM": "Warehouse Management (창고 관리)",
    "PS": "Project System (프로젝트 시스템)",
    "EWM": "Extended Warehouse Management (확장 창고)",
    "Basis": "Basis / Technical",
}

_DEVTYPE_LABELS = {
    "Report_ALV": "Report / ALV 조회 프로그램",
    "Dialog": "Dialog Program (다이얼로그)",
    "Function_Module": "Function Module",
    "Enhancement": "BAdI / User Exit (Enhancement)",
    "BAPI": "BAPI 호출 프로그램",
    "Data_Upload": "데이터 업로드 (BDC/LSMW)",
    "Interface": "인터페이스 (IDoc/RFC)",
    "Form": "출력 서식 (SmartForms/Adobe Forms)",
    "Workflow": "Workflow",
    "Fiori_Web": "Fiori / Web Dynpro",
}


# ── LLM 초기화 ────────────────────────────────────────

def _get_llm() -> LLM:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    os.environ.setdefault("GEMINI_API_KEY", api_key)
    mid = get_gemini_model_id()
    return LLM(model=f"gemini/{mid}", api_key=api_key)


# ── 에이전트 팩토리 ───────────────────────────────────

def _make_agents(llm: LLM):
    f_analyst = Agent(
        role="SAP 요구사항 분석가",
        goal="고객 RFP와 인터뷰 답변을 분석하여 구조화된 요구사항 현황을 도출한다",
        backstory="""당신은 Hannah입니다. SAP 프로젝트 요구사항 분석 전문가로,
고객의 말 속에서 기술적 요구사항을 정확히 파악합니다.
분석 결과는 항상 체계적으로 구조화하며, 불명확한 부분은 명시적으로 표시합니다.
10년 이상의 SAP 프로젝트 경험을 바탕으로 현실적인 요구사항 분석을 제공합니다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    f_questioner = Agent(
        role="SAP 인터뷰 전문가",
        goal="고객이 쉽게 답할 수 있는 실무적인 인터뷰 질문 3개를 생성한다",
        backstory="""당신은 Mia입니다. 수백 건의 SAP 프로젝트 요구사항 인터뷰를 진행한 경험이 있습니다.
비즈니스 의사결정에 직결되는 구체적인 질문을 만들며,
고객(IT 비전문가)도 쉽게 이해하고 답할 수 있는 언어로 작성합니다.

좋은 질문 형식 예시:
- "기능이 필요한가요? (예: 옵션1, 옵션2) 필요하다면 어떤 기준으로?"
- "특정 상태를 어떻게 정의하나요? (예: 전체 납품 완료, Invoice 발행 완료)"
- "추가 출력 형식이 필요한가요? (예: 엑셀 다운로드, 인쇄)"

반드시 JSON 형식으로만 출력합니다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    f_writer = Agent(
        role="개발 제안서 작성 전문가",
        goal="비전문가 고객도 만족할 수 있는 전문적인 Development Proposal을 작성한다",
        backstory="""당신은 Jun입니다. SAP 컨설팅 경험과 뛰어난 문서 작성 능력을 겸비했습니다.
고객이 '내 요구사항이 정확히 이해되었구나'라고 느낄 수 있는 제안서를 작성합니다.
IT 전문 용어는 고객 친화적 언어로 풀어서 설명하며,
개발 결과물이 비즈니스에 어떤 가치를 제공하는지 명확히 기술합니다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    f_reviewer = Agent(
        role="제안서 품질 검토 전문가",
        goal="Development Proposal의 완성도를 검토하고 최종 품질을 보장한다",
        backstory="""당신은 Sara입니다. SAP 프로젝트 제안서 수십 건을 검토한 품질 관리자입니다.
필수 항목 누락, 모호한 표현, 고객 혼란 유발 요소를 즉시 포착합니다.
검토 후 보완이 필요한 부분은 직접 수정하여 완성도 높은 Proposal을 출력합니다.
반드시 [APPROVED] 태그로 시작하는 최종본을 출력합니다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    return f_analyst, f_questioner, f_writer, f_reviewer


# ── 헬퍼 ─────────────────────────────────────────────

def _fmt_rfp(rfp: dict) -> str:
    modules = [_MODULE_LABELS.get(m, m) for m in rfp.get("sap_modules", [])]
    devtypes = [_DEVTYPE_LABELS.get(d, d) for d in rfp.get("dev_types", [])]
    return (
        f"- 요청 제목: {rfp.get('title', '(없음)')}\n"
        f"- SAP 모듈: {', '.join(modules) or '(미선택)'}\n"
        f"- 개발 유형: {', '.join(devtypes) or '(미선택)'}\n"
        f"- 요구사항:\n{rfp.get('description', '(없음)')}"
    )


def _fmt_conv(conv: list[dict]) -> str:
    if not conv:
        return "(인터뷰 없음)"
    parts = []
    for m in conv:
        parts.append(f"\n[{m['round_number']}라운드 질문]")
        for i, q in enumerate(m["questions"], 1):
            parts.append(f"  Q{i}. {q}")
        if m.get("answers_text"):
            parts.append(f"[{m['round_number']}라운드 답변]\n  {m['answers_text']}")
    return "\n".join(parts)


def _parse_questions(raw: str) -> list[str]:
    """크루 출력에서 질문 JSON을 추출합니다."""
    text = raw.strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    try:
        m = re.search(r'\{[\s\S]*?"questions"[\s\S]*?\}', text)
        if m:
            return json.loads(m.group()).get("questions", [])
    except Exception:
        pass
    # 줄 단위 파싱 폴백
    questions = [ln.strip().lstrip('"-').strip()
                 for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith(("{", "}", "[", "]"))]
    return [q for q in questions if len(q) > 10][:3]


_DEFAULT_QUESTIONS = [
    "이 개발의 주요 사용자는 누구인가요? (예: 영업팀, 물류팀, 경영진)",
    "조회 결과를 엑셀로 다운로드하거나 인쇄하는 기능이 필요한가요?",
    "기존에 유사한 프로그램이 있나요? 있다면 어떤 점을 개선하고 싶으신가요?",
]


# ── Public API ────────────────────────────────────────

def generate_round_questions(
    rfp_data: dict,
    conversation: list[dict],
    round_num: int,
    code_library_context: str = "",
) -> dict:
    """
    한 라운드의 인터뷰 질문 3개를 생성합니다.
    1라운드이고 코드 라이브러리 매칭이 있으면 그 질문을 우선 사용합니다.

    Returns:
        {"questions": [...], "is_complete": False, "source": "..."}
    """
    analysis_summary, lib_ctx = _parse_code_library_context(code_library_context)

    # 1라운드: 코드 라이브러리 질문 우선 사용
    if round_num == 1 and code_library_context:
        try:
            ctx = lib_ctx if lib_ctx else json.loads(code_library_context)
            qs = ctx.get("questions", [])
            if qs:
                return {
                    "questions": qs[:3],
                    "is_complete": False,
                    "source": ctx.get("source", "코드 라이브러리 기반"),
                }
        except Exception:
            pass

    llm = _get_llm()
    f_analyst, f_questioner, _, _ = _make_agents(llm)
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)

    lib_for_hannah = ""
    if analysis_summary:
        lib_for_hannah = f"""

[서버 코드 라이브러리 – 유사 프로그램 요약 (고객 PC 로컬 참고 코드와 별개, 패턴 참고용)]
{analysis_summary}
"""

    # Task 1: Hannah – 현재 상태 분석
    analyze_task = Task(
        description=f"""아래 RFP와 지금까지의 인터뷰 내용을 분석하세요.

[RFP 정보]
{rfp_ctx}

[인터뷰 내용]
{conv_ctx}
{lib_for_hannah}
[현재 라운드: {round_num} / 전체: {MAX_ROUNDS}]

다음 항목을 간결하게 분석하세요:
1. 현재까지 파악된 핵심 요구사항 (2~3줄)
2. 아직 불명확하거나 확인이 필요한 사항 목록
3. 이번 라운드에서 반드시 확인해야 할 우선순위 3가지

※ 서버 코드 라이브러리 요약이 있다면, 그 사례와 고객 RFP의 차이·공통점을 구분해 분석에 반영하세요.""",
        agent=f_analyst,
        expected_output="요구사항 현황 분석 결과 (텍스트)",
    )

    # Task 2: Mia – 질문 생성
    question_task = Task(
        description=f"""Hannah의 분석을 바탕으로 {round_num}라운드 인터뷰 질문 3개를 생성하세요.

[코드 라이브러리 참고 자료]
{_format_library_block_for_mia(code_library_context)}

작성 원칙:
- "기능이 필요한가요? (예: 구체적 사례) 필요하다면 어떤 기준으로?" 구조
- 고객(비개발자)이 이해하고 답할 수 있는 언어
- 개발 방향이 달라지는 비즈니스 의사결정에 집중
- 이미 답변된 내용은 다시 묻지 마세요

반드시 아래 JSON 형식으로만 출력:
{{"questions": ["질문1", "질문2", "질문3"]}}""",
        agent=f_questioner,
        expected_output='{"questions": ["질문1", "질문2", "질문3"]}',
        context=[analyze_task],
    )

    crew = Crew(
        agents=[f_analyst, f_questioner],
        tasks=[analyze_task, question_task],
        process=Process.sequential,
        verbose=False,
    )

    try:
        result = crew.kickoff()
        questions = _parse_questions(str(result))
    except Exception:
        questions = []

    if not questions:
        questions = _DEFAULT_QUESTIONS

    return {
        "questions": questions[:3],
        "is_complete": False,
        "source": "AI 에이전트 생성 (Hannah + Mia)",
    }


def generate_proposal(
    rfp_data: dict,
    conversation: list[dict],
    code_library_context: str = "",
) -> str:
    """
    전체 인터뷰 내용으로 Development Proposal을 생성합니다.
    Hannah(최종 분석) → Jun(작성) → Sara(검토/승인) 순서로 진행합니다.
    """
    llm = _get_llm()
    f_analyst, _, f_writer, f_reviewer = _make_agents(llm)
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)
    analysis_summary, _ = _parse_code_library_context(code_library_context)
    lib_for_hannah = ""
    if analysis_summary:
        lib_for_hannah = f"""

[서버 코드 라이브러리 – 유사 프로그램 요약 (Proposal 기술·화면 설계 참고; 고객 로컬 참고 코드 미포함)]
{analysis_summary}
"""

    # Task 1: Hannah – 최종 요구사항 명세
    final_analysis = Task(
        description=f"""아래 RFP와 전체 인터뷰 내용을 분석하여 최종 요구사항 명세를 작성하세요.

[RFP 정보]
{rfp_ctx}
{lib_for_hannah}
[전체 인터뷰 내용]
{conv_ctx}

다음 항목을 포함한 구조화된 분석 결과를 작성하세요:
1. 프로그램 목적 및 배경
2. 핵심 기능 요구사항 목록
3. 입력 조건 및 출력 형태
4. SAP 모듈/컴포넌트 범위
5. 특이사항 및 제약조건
6. 복잡도 평가 (Low/Medium/High) 및 근거

※ 코드 라이브러리 요약이 있으면, 유사 사례의 화면·기술 패턴을 참고하되 고객 RFP·인터뷰 내용을 최우선으로 반영하세요.""",
        agent=f_analyst,
        expected_output="구조화된 최종 요구사항 명세 (텍스트)",
    )

    # Task 2: Jun – Proposal 작성
    write_task = Task(
        description="""Hannah의 요구사항 명세를 바탕으로 Development Proposal을 작성하세요.

아래 6개 섹션을 마크다운 형식으로 반드시 포함하세요:

# Development Proposal

## 1. 개발 개요
- 프로그램명 (제안): Z 또는 Y로 시작하는 SAP 커스텀 프로그램명
- 개발 목적 및 배경
- 기대 효과 (비즈니스 관점으로 서술)
- 관련 SAP 표준 프로세스 및 T-Code

## 2. 구현 기능
(고객이 이해할 수 있는 언어로 기능 목록 작성, 각 기능의 비즈니스 가치 포함)

## 3. 화면 구성
- 조회 조건 입력 항목 목록 (필드명, 필수여부)
- 결과 화면 표시 항목 목록

## 4. 처리 흐름
(1번부터 단계별로 프로그램 실행 흐름 기술, 최대 7단계)

## 5. 기술 사항
- 활용 SAP 컴포넌트 (T-Code, BAPI, 주요 테이블)
- 예상 개발 규모 (Small/Medium/Large)

## 6. 확인 필요 사항
(구현 전 고객과 반드시 확인해야 할 사항 목록)

작성 원칙: IT 비전문가도 이해 가능한 언어, SAP 용어는 괄호 안에 간단한 설명 추가""",
        agent=f_writer,
        expected_output="완성된 Development Proposal (마크다운)",
        context=[final_analysis],
    )

    # Task 3: Sara – 검토 및 최종 승인
    review_task = Task(
        description="""Jun이 작성한 Development Proposal을 검토하세요.

체크리스트:
□ 6개 필수 섹션 (개발 개요, 구현 기능, 화면 구성, 처리 흐름, 기술 사항, 확인 필요 사항) 모두 포함
□ 프로그램명 (Z/Y로 시작) 포함
□ 기대 효과가 비즈니스 언어로 구체적으로 기술
□ 화면 구성이 구체적 (추상적 표현 없음)
□ IT 비전문가가 이해하기 어려운 표현 없음
□ 확인 필요 사항이 실질적이고 구체적

보완이 필요한 항목은 직접 수정하여 완성본을 출력하세요.
반드시 아래 형식으로 시작하세요:

[APPROVED]
(수정/보완된 최종 Proposal 전체 내용)""",
        agent=f_reviewer,
        expected_output="[APPROVED]로 시작하는 최종 검토 완료 Proposal",
        context=[write_task],
    )

    crew = Crew(
        agents=[f_analyst, f_writer, f_reviewer],
        tasks=[final_analysis, write_task, review_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    raw = str(result).strip()

    if raw.startswith("[APPROVED]"):
        raw = raw[len("[APPROVED]"):].strip()

    return raw


# ── 코드 라이브러리 분석 (Hannah → Mia) ─────────────────

def analyze_code_for_library(
    source_code: str,
    title: str,
    modules: list[str],
    dev_types: list[str],
) -> dict:
    """
    ABAP 소스를 Hannah(기술 분석)→ Mia(범용 질문 추출) 2단계로 분석합니다.
    반환 dict는 DB `analysis_json`에 저장되며, 상세 화면은 `codelib_detail.html`에서 표시한다.

    Returns:
        program_purpose, screens[], validations, key_bapis, key_fms, applied_techniques, questions, error
        (+ 구 JSON 호환용 selection_screen, result_screen 키는 비어 있거나 LLM이 채울 수 있음)
    """
    llm = _get_llm()
    f_analyst, f_questioner, _, _ = _make_agents(llm)

    module_str  = ", ".join(modules)
    devtype_str = ", ".join(dev_types)
    code_excerpt = _trim_code(source_code)

    # ── Task 1: Hannah – 기술 분석 ────────────────────────
    analysis_task = Task(
        description=f"""아래 ABAP 소스 코드를 전문가 수준으로 분석하세요.

[프로그램 정보]
- 제목: {title}
- SAP 모듈: {module_str}
- 개발 유형: {devtype_str}

[ABAP 소스]
{code_excerpt}

다음 규칙을 지켜 반드시 아래 JSON 형식으로만 출력하세요.
- 출력은 유효한 JSON 객체 하나뿐입니다. JSON 앞뒤에 서론·결론·마크다운 제목을 쓰지 마세요.
- "program_purpose"에 위 [프로그램 정보]의 제목만 그대로 넣지 마세요. 소스 분석에 근거한 목적·역할을 2~3문장으로 서술하세요.
- "screens" 배열에는 이 프로그램에서 식별한 UI·실행 면을 최소 1개 포함하세요. (순수 배치면 그 성격을 한 항목으로 명시)
한국어로 작성하되, 기술 용어(BAPI명, FM명, 필드명, 화면 번호 등)는 영문 그대로 사용하세요.

★ 스크린 분석 (매우 중요)
- "실행 조건 화면 / 실행 결과 화면" 같은 고정 2분류를 쓰지 마세요. 프로그램마다 UI가 다릅니다.
- 소스에서 식별되는 사용자에게 보이는 모든 스크린·UI 면을 나열하세요. 예:
  SELECTION-SCREEN, 각 dynpro(SCREEN 0100 등), ALV/리스트/그리드 화면, 팝업(CALL SCREEN, POPUP),
  다이얼로그, OO ALV 컨테이너, Web Dynpro 화면(있다면) 등.
- 스크린이 논리적으로 하나뿐이면(예: 순수 배치) screens 배열에 항목 1개만 두고 title에 그 성격을 적으세요.
- 각 스크린마다:
  - screen_key: 소스에서 구분할 수 있는 짧은 식별(예: "0100", "SELECTION-SCREEN", "POPUP_VENDOR")
  - title: 그 스크린을 한 줄로 요약한 제목(타이틀 느낌, 80자 이내 권장)
  - summary_bullets: 그 스크린의 주요 기능·동작만 불릿으로 2~6개. 각 문자열은 한 문장 이내 요약.
    서술형 장문 넣지 말고, 읽기 좋게 핵심만.

{{
  "program_purpose": "프로그램 목적과 기능을 2~3문장으로 설명",
  "screens": [
    {{
      "screen_key": "식별자",
      "title": "스크린 한 줄 요약 제목",
      "summary_bullets": ["기능 요약 1", "기능 요약 2"]
    }}
  ],
  "validations": ["Validation 로직 1", "Validation 로직 2"],
  "key_bapis": ["BAPI_명1"],
  "key_fms": ["FM명1"],
  "applied_techniques": ["적용 기법 1 (예: ALV 색상 강조)", "적용 기법 2 (예: 대용량 처리를 위한 패키지 처리)"]
}}""",
        agent=f_analyst,
        expected_output="기술 분석 JSON",
    )

    # ── Task 2: Mia – 범용 인터뷰 질문 추출 ──────────────
    question_task = Task(
        description=f"""Hannah의 분석을 바탕으로,
"{module_str} + {devtype_str}" 유형의 개발을 요청하는 신규 고객에게
공통으로 물어야 할 인터뷰 질문 3~5개를 추출하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 반드시 이 4개 예시와 동일한 형식과 수준으로 작성하세요
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[예시 1] 데이터 마스킹 처리(고객 정보, 가격 정보 등)가 필요한 필드가 있나요?
         있다면, 어떤 규칙으로 마스킹해야 할까요?

[예시 2] 보고서에서 '완료'로 간주되는 상태는 무엇인가요?
         (예: 전체 납품 완료, 전체 Invoice 발행 완료)
         이 상태를 기준으로 데이터를 필터링하거나 특정 색상으로 강조 표시해야 할까요?

[예시 3] 특정 이슈(예: 납기 지연, 재고 부족, 반품)를 강조 표시해야 하나요?
         있다면 어떤 기준으로 판단해야 하나요?

[예시 4] ALV 그리드 외에 추가 데이터 시각화(예: 차트, 그래프)가 필요한가요?
         필요하다면 어떤 종류가 유용할까요? (예: 기간별 추이, 지역별 현황)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 좋은 질문의 3가지 원칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. "기능이 필요한가요? (예: 구체적 사례)" 구조 – 고객이 Yes/No 후 세부사항 답변 가능
2. 괄호 안에 구체적 예시 포함 – 고객이 어떤 답을 해야 하는지 힌트 제공
3. 어느 회사에서나 구현 방식이 달라질 수 있는 비즈니스 의사결정 사항

★ 절대 피할 것: 특정 코드의 하드코딩 값/임계치, 개발자가 혼자 결정하는 사항

반드시 아래 JSON 형식으로만 출력:
{{"questions": ["질문1", "질문2", "질문3", "질문4", "질문5"]}}""",
        agent=f_questioner,
        expected_output='{"questions": ["질문1", ...]} 형식 JSON',
        context=[analysis_task],
    )

    crew = Crew(
        agents=[f_analyst, f_questioner],
        tasks=[analysis_task, question_task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        crew.kickoff()

        analysis_raw = _crew_task_output_text(analysis_task)
        question_raw = _crew_task_output_text(question_task)

        analysis_data = _parse_json_block(analysis_raw, default={})
        question_data = _parse_json_block(question_raw, default={"questions": []})

        incomplete = (not analysis_data) or (
            not _analysis_looks_complete(analysis_data, title)
        )
        raw_ok = bool((analysis_raw or "").strip())

        if incomplete:
            base = {
                "program_purpose": title,
                "screens": [],
                "selection_screen": {},
                "result_screen": {},
                "validations": [],
                "key_bapis": [],
                "key_fms": [],
                "applied_techniques": [],
                "questions": question_data.get("questions", []),
            }
            if not raw_ok:
                return {
                    **base,
                    "error": (
                        "Hannah 분석 응답 텍스트를 찾지 못했습니다. "
                        "CrewAI 출력 필드가 비어 있거나 형식이 바뀌었을 수 있습니다."
                    ),
                }
            if not analysis_data:
                return {
                    **base,
                    "error": (
                        "Hannah 분석 응답을 JSON으로 읽지 못했습니다. "
                        "잠시 후 재분석하거나, 서버 로그에서 Crew 출력을 확인해 주세요."
                    ),
                }
            return {
                **base,
                "error": (
                    "분석 JSON에 화면·검증·인터페이스 등 구조화된 항목이 없습니다. "
                    "모델이 요청한 스키마를 따르지 않았을 수 있으니 재분석해 주세요."
                ),
            }

        screens = _normalize_library_screens(analysis_data.get("screens"))

        return {
            "program_purpose": analysis_data.get("program_purpose", title),
            "screens": screens,
            "selection_screen": analysis_data.get("selection_screen") or {},
            "result_screen": analysis_data.get("result_screen") or {},
            "validations": analysis_data.get("validations", []),
            "key_bapis": analysis_data.get("key_bapis", []),
            "key_fms": analysis_data.get("key_fms", []),
            "applied_techniques": analysis_data.get("applied_techniques", []),
            "questions": question_data.get("questions", []),
            "error": None,
        }

    except Exception as e:
        return {
            "program_purpose": title,
            "screens": [],
            "selection_screen": {},
            "result_screen": {},
            "validations": [],
            "key_bapis": [],
            "key_fms": [],
            "applied_techniques": [],
            "questions": [],
            "error": str(e),
        }


def _normalize_library_screens(raw) -> list:
    """LLM이 반환한 screens 배열을 dict 목록으로 정리합니다."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = (item.get("screen_key") or item.get("id") or "").strip() or "—"
        title = (item.get("title") or "").strip()
        bullets = item.get("summary_bullets") or item.get("bullets") or item.get("details")
        if isinstance(bullets, str):
            bullets = [b.strip().lstrip("-• ").strip() for b in bullets.split("\n") if b.strip()]
        elif not isinstance(bullets, list):
            bullets = []
        else:
            bullets = [str(b).strip().lstrip("-• ").strip() for b in bullets if str(b).strip()]
        if not title and not bullets:
            continue
        out.append({"screen_key": key, "title": title or key, "summary_bullets": bullets})
    return out


def _crew_task_output_text(task) -> str:
    """CrewAI 버전에 따라 Task 출력이 raw / result 등 다른 속성에 있을 수 있어 문자열을 뽑습니다."""
    out = getattr(task, "output", None)
    if out is None:
        return ""
    if isinstance(out, str):
        return out
    raw = getattr(out, "raw", None)
    if isinstance(raw, str) and raw.strip():
        return raw
    for attr in ("exported_output", "result", "final_output"):
        v = getattr(out, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    pyd = getattr(out, "pydantic", None)
    if pyd is not None:
        try:
            if hasattr(pyd, "model_dump"):
                d = pyd.model_dump()
            else:
                d = dict(pyd) if hasattr(pyd, "__iter__") else {}
            for k in ("raw", "description", "final_output", "output"):
                v = d.get(k) if isinstance(d, dict) else None
                if isinstance(v, str) and v.strip():
                    return v
        except Exception:
            pass
    s = str(out)
    return s if s and s != "None" else ""


def _analysis_looks_complete(data: dict, upload_title: str = "") -> bool:
    """스키마상 최소 의미 있는 분석인지(제목 한 줄만 반복된 경우 제외)."""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("screens"), list) and len(data.get("screens") or []) > 0:
        return True
    for k in ("validations", "key_bapis", "key_fms", "applied_techniques"):
        v = data.get(k)
        if isinstance(v, list) and len(v) > 0:
            return True
    ss, rs = data.get("selection_screen") or {}, data.get("result_screen") or {}
    if isinstance(ss, dict) and len(ss) > 0:
        return True
    if isinstance(rs, dict) and len(rs) > 0:
        return True
    purpose = (data.get("program_purpose") or "").strip()
    ut = (upload_title or "").strip()
    if ut and purpose.lower() == ut.lower():
        return False
    if purpose and len(purpose) > len(ut) + 40:
        return True
    return False


def _trim_code(source_code: str, max_lines: int = 300) -> str:
    """코드가 길 경우 핵심 섹션(선언부 + 주요 로직)만 추출합니다."""
    lines = source_code.splitlines()
    if len(lines) <= max_lines:
        return source_code

    head = lines[:50]
    keywords = [
        "SELECTION-SCREEN", "PARAMETERS", "SELECT-OPTIONS",
        "SCREEN ", "MODULE ", "CALL SCREEN",
        "CALL FUNCTION", "BAPI_", "BAPI ",
        "FORM ", "ENDFORM", "LOOP AT", "READ TABLE",
        "MESSAGE", "RETURN",
    ]
    important = []
    for i, line in enumerate(lines[50:], start=50):
        if any(kw in line.upper() for kw in keywords):
            important.extend(lines[max(50, i-2):min(len(lines), i+5)])

    tail = lines[-30:]
    combined = head + ["... (중략) ..."] + list(dict.fromkeys(important)) + ["... (중략) ..."] + tail
    return "\n".join(combined[:max_lines])


def _parse_json_block(text: str, default) -> dict:
    """텍스트에서 첫 번째 유효한 JSON 객체(dict)를 파싱합니다. 중첩·코드펜스·앞뒤 잡음에 강합니다."""
    if not text or not str(text).strip():
        return default
    text = str(text).strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return default
