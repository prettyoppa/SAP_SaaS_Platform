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

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MAX_ROUNDS = 3

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
    return LLM(model="gemini/gemini-2.0-flash", api_key=api_key)


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
    # 1라운드: 코드 라이브러리 질문 우선 사용
    if round_num == 1 and code_library_context:
        try:
            ctx = json.loads(code_library_context)
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

    # Task 1: Hannah – 현재 상태 분석
    analyze_task = Task(
        description=f"""아래 RFP와 지금까지의 인터뷰 내용을 분석하세요.

[RFP 정보]
{rfp_ctx}

[인터뷰 내용]
{conv_ctx}

[현재 라운드: {round_num} / 전체: {MAX_ROUNDS}]

다음 항목을 간결하게 분석하세요:
1. 현재까지 파악된 핵심 요구사항 (2~3줄)
2. 아직 불명확하거나 확인이 필요한 사항 목록
3. 이번 라운드에서 반드시 확인해야 할 우선순위 3가지""",
        agent=f_analyst,
        expected_output="요구사항 현황 분석 결과 (텍스트)",
    )

    # Task 2: Mia – 질문 생성
    question_task = Task(
        description=f"""Hannah의 분석을 바탕으로 {round_num}라운드 인터뷰 질문 3개를 생성하세요.

[코드 라이브러리 참고 질문]
{code_library_context if code_library_context else "없음"}

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


def generate_proposal(rfp_data: dict, conversation: list[dict]) -> str:
    """
    전체 인터뷰 내용으로 Development Proposal을 생성합니다.
    Hannah(최종 분석) → Jun(작성) → Sara(검토/승인) 순서로 진행합니다.
    """
    llm = _get_llm()
    f_analyst, _, f_writer, f_reviewer = _make_agents(llm)
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)

    # Task 1: Hannah – 최종 요구사항 명세
    final_analysis = Task(
        description=f"""아래 RFP와 전체 인터뷰 내용을 분석하여 최종 요구사항 명세를 작성하세요.

[RFP 정보]
{rfp_ctx}

[전체 인터뷰 내용]
{conv_ctx}

다음 항목을 포함한 구조화된 분석 결과를 작성하세요:
1. 프로그램 목적 및 배경
2. 핵심 기능 요구사항 목록
3. 입력 조건 및 출력 형태
4. SAP 모듈/컴포넌트 범위
5. 특이사항 및 제약조건
6. 복잡도 평가 (Low/Medium/High) 및 근거""",
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
    code_analyzer.analyze_abap_code()와 동일한 dict 형식을 반환합니다.

    Returns:
        {
            "program_purpose": str,
            "key_bapis": [...],
            "key_fms": [...],
            "input_fields": [...],
            "output_type": str,
            "key_logics": [...],
            "questions": [...],
            "error": None | str
        }
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

다음 항목을 분석하여 반드시 아래 JSON 형식으로만 출력하세요.
한국어로 작성하되, 기술 용어(BAPI명, FM명, 필드명 등)는 영문 그대로 사용하세요.

{{
  "program_purpose": "프로그램 목적과 기능을 2~3문장으로 설명",
  "selection_screen": {{
    "layout": "조건 화면 레이아웃 설명 (예: 상단에 회사코드/플랜트 필수 입력, 날짜 범위, 기타 조건 등)",
    "fields": ["필드명1 (SAP필드명, 필수/선택)", "필드명2 ..."]
  }},
  "result_screen": {{
    "layout": "결과 화면 레이아웃 설명 (예: ALV Grid로 출력, 합계행 포함, 색상 강조 등)",
    "columns": ["컬럼명1", "컬럼명2 ..."]
  }},
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

        # TaskOutput.raw 로 각 task 결과 텍스트 추출
        analysis_raw = (analysis_task.output.raw or "") if analysis_task.output else ""
        question_raw = (question_task.output.raw or "") if question_task.output else ""

        analysis_data = _parse_json_block(analysis_raw, default={})
        question_data = _parse_json_block(question_raw, default={"questions": []})

        return {
            "program_purpose": analysis_data.get("program_purpose", title),
            "selection_screen": analysis_data.get("selection_screen", {}),
            "result_screen": analysis_data.get("result_screen", {}),
            "validations": analysis_data.get("validations", []),
            "key_bapis":   analysis_data.get("key_bapis", []),
            "key_fms":     analysis_data.get("key_fms", []),
            "applied_techniques": analysis_data.get("applied_techniques", []),
            "questions":   question_data.get("questions", []),
            "error":       None,
        }

    except Exception as e:
        return {
            "program_purpose": title,
            "selection_screen": {}, "result_screen": {},
            "validations": [], "key_bapis": [], "key_fms": [],
            "applied_techniques": [], "questions": [],
            "error": str(e),
        }


def _trim_code(source_code: str, max_lines: int = 300) -> str:
    """코드가 길 경우 핵심 섹션(선언부 + 주요 로직)만 추출합니다."""
    lines = source_code.splitlines()
    if len(lines) <= max_lines:
        return source_code

    head = lines[:50]
    keywords = [
        "SELECTION-SCREEN", "PARAMETERS", "SELECT-OPTIONS",
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
    """텍스트에서 JSON 블록을 추출합니다."""
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return default
