"""
Paid Tier — FS·납품 ABAP

- FS: CrewAI / Gemini (대외명 「FS설계」 에이전트, 내부 role p_architect). 키 없으면 예외만(가짜 문서 없음).
- 납품 ABAP: 「ABAP」→「코드검수」→「테스트」 순 CrewAI·Gemini 호출. 키 필수.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from .free_crew import (
    _MEMBER_FACING_NO_STORAGE_NAMES,
    _fmt_conv,
    _fmt_rfp,
    _get_llm,
    _lib_block_heading,
    _parse_code_library_context,
)
from ..agent_display import agent_label_ko
from ..gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def _truncate(s: str, max_len: int) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + f"\n\n…(이하 약 {len(t) - max_len}자 생략)"


def _tail_for_followup_prompt(s: str, max_chars: int = 118_000) -> str:
    """납품 코드 순차 단계로 프로프트에 넘길 때 이전 출력 길이 제한(후반 위주 유지)."""
    b = s or ""
    if len(b) <= max_chars:
        return b
    note = "\n…(위쪽 원문 일부 생략 — ABAP 블록은 보통 후반부)…\n"
    avail = max_chars - len(note)
    return note + b[-avail:]


def generate_fs_markdown(
    rfp_data: dict[str, Any],
    conversation: list[dict],
    proposal_text: str,
    *,
    code_library_context: str = "",
    member_safe_output: bool = False,
) -> str:
    """
    기능명세(FS) 설계: 요구(RFP)·질의응답·제안서(참고)를 교차 검토해 상세 FS 마크다운 작성.
    GOOGLE_API_KEY 없으면 _get_llm()에서 즉시 RuntimeError — 가짜 FS 문서를 반환하지 않는다.
    """
    llm = _get_llm()
    fs_spec_agent = Agent(
        role="SAP 기능명세(FS)·상세설계 책임자",
        goal="요구분석·인터뷰·제안서를 교차검증하고 개발 착수 가능한 상세 기능명세를 만든다",
        backstory="""당신은 대형 ERP SI에서 FS/상세설계를 수십 건 작성한 리드 컨설턴트다.
'Development Proposal'은 고객용 개괄 문서이고, 당신의 산출물은 **구현 설계서**다.
제안서의 문장·표를 **복사해 붙이지 말고**, RFP·인터뷰와 대조해 누락·모순을 드러내며 **새로** 상세 명세를 쓴다.
한국어 SAP 실무 용어를 쓰고, 화면은 필드 단위 표로, 검증·권한·예외를 구체화한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _truncate(_fmt_conv(conversation), 52000)
    prop_block = _truncate(proposal_text or "", 72000)
    analysis_summary, _ = _parse_code_library_context(code_library_context)
    lib_for = ""
    if analysis_summary:
        lib_for = f"\n\n{_lib_block_heading(member_safe_output)}\n{analysis_summary}"
    member_ref = (rfp_data.get("reference_code_for_agents") or "").strip()
    ref_body_fs = member_ref if member_ref else "(고객 참고 ABAP 미첨부)"
    _ms = _MEMBER_FACING_NO_STORAGE_NAMES if member_safe_output else ""

    pid = (rfp_data.get("program_id") or "").strip()
    tcode = (rfp_data.get("transaction_code") or "").strip()
    id_rules = ""
    if pid or tcode:
        id_rules = f"""
**고객 지정 식별자(필수):**
- 프로그램 ID: `{pid or "없음"}` — 있으면 문서 전체에서 **이 식별자만** 사용. 다른 Z/Y 이름을 임의로 만들지 않는다.
- T-Code: `{tcode or "없음"}` — 있으면 실행/호출 진입점은 **이 코드만** 기술한다.
"""

    task = Task(
        description=f"""아래 (1)(1b)(2)(3)을 **모두** 읽고 교차검증하라. 서로 모순되면 FS 끝에 **오픈 이슈**로 적시하라.

**구분(필수):** (1)은 서면 요구만이다. (1b)는 회원이 **요청 제출 시** 참고로 첨부한 **원본 ABAP**이며, **귀하가 작성하는 FS 본문이나 이후 납품 ABAP 자동생성 결과가 아니다.** FS에 넣을 예시·pseudo 코드는 (1b)를 복사하지 말고 **설계 관점에서 새로** 쓴다.

### (1) RFP 원천 요구 (텍스트·모듈·설명만)
{rfp_ctx}
{lib_for}

### (1b) 고객 참고 ABAP (요청 폼에 **직접 첨부**한 원본 — FS·납품 산출물 **아님**)
{ref_body_fs}

### (2) 인터뷰 — 질의·고객 답변 전체
{conv_ctx}

### (3) 이미 발행된 Development Proposal (고객안)
이 문서는 **맥락 정렬·누락 점검용**이다.
**절대 요약이나 표·문장을 그대로 복사해 FS에 붙이지 마라.** FS는 설계 산출물로 **새로 작성**한다.

{prop_block}

{_ms}
{id_rules}

**모델 참고**: `{get_gemini_model_id()}`. 불명확한 SAP 전제는 오픈 이슈로 남겨라.

출력: **단일 마크다운** 문서. 첫 제목 줄은 반드시 `# 기능명세서 (FS)` 로 시작.

권장 목차:
### 1. 목적·범위·전제
### 2. 용어
### 3. 업무 프로세스·후속 트랜잭션 연계
### 4. 프로그램·진입점 (Report / ALV / Dialog 등)
### 5. 화면 명세 — 필드 단위 마크다운 표
### 6. 선택화면·variant·초기값
### 7. 조회·저장·업무 검증 규칙·메시지
### 8. 권한·통제
### 9. 인터페이스 / RFC·BAPI·배치
### 10. 예외·에러·로그
### 11. 데이터량·성능 가정
### 12. 테스트 포인트
### 13. 오픈 이슈·고객 확인 필요

규칙: 마케팅 문장 금지. 추정 사항은 "가정:" 표시.
""",
        agent=fs_spec_agent,
        expected_output="완결된 기능명세서 마크다운 본문",
    )

    crew = Crew(
        agents=[fs_spec_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
    return str(crew.kickoff()).strip()


def generate_delivered_abap_markdown(
    rfp_data: dict[str, Any],
    fs_text: str,
    proposal_text: str,
    conversation: list[dict],
    *,
    code_library_context: str = "",
    member_safe_output: bool = False,
    phase_log: Callable[[str], None] | None = None,
) -> str:
    """
    「ABAP」→「코드검수」→「테스트」 순으로 Gemini 호출(단계별 Crew).
    키 없으면 _get_llm()에서 RuntimeError — placeholder 소스 없음.
    """
    llm = _get_llm()

    def _ph(msg: str) -> None:
        if phase_log:
            phase_log(msg)

    abap_agent = Agent(
        role="SAP ABAP 시니어 개발자",
        goal="기능명세서에 맞춰 구조화된 ABAP 초안을 작성한다",
        backstory="""당신은 15년차 ABAP 개발자로 Report/ALV/Dialog·모듈 풀을 다룬다.
산출물은 **실제 시스템에 넣고 문법·정적 검토를 통과시키려는 초안** 수준이어야 한다.
불확실한 객체(테이블·함수)는 주석으로 표시하고, 추측으로 위험한 DDIC 참조는 피한다.
한국어 주석으로 의도를 설명한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    rfp_ctx = _fmt_rfp(rfp_data)
    fs_block = _truncate(fs_text or "", 96000)
    prop_snip = _truncate(proposal_text or "", 16000)
    conv_snip = _truncate(_fmt_conv(conversation), 24000)
    analysis_summary, _ = _parse_code_library_context(code_library_context)
    lib_for = ""
    if analysis_summary:
        lib_for = f"\n\n{_lib_block_heading(member_safe_output)}\n{_truncate(analysis_summary, 8000)}"
    member_ref = (rfp_data.get("reference_code_for_agents") or "").strip()
    ref_for_prompt = member_ref if member_ref else "(고객 참고 ABAP 미첨부)"
    _ms = _MEMBER_FACING_NO_STORAGE_NAMES if member_safe_output else ""

    pid = (rfp_data.get("program_id") or "").strip()
    cust_pid = pid
    tcode = (rfp_data.get("transaction_code") or "").strip()

    kevin_task = Task(
        description=f"""아래 **기능명세서(FS)** 를 1차 구현 기준으로 삼아 ABAP 초안을 작성하라.
RFP·인터뷰·제안서는 FS와 충돌 시 **FS를 우선**한다.

**역할 구분(반드시 준수):**
- **「고객 참고 ABAP」** 블록: 회원이 **요청 제출 시** 폼에 넣은 **참고용 원본**이다. **납품 ABAP 초안이 아니며**, 출력물로 되돌려 제시할 코드가 아니다.
- **「기능명세서(FS)」** 블록: {agent_label_ko("p_architect")}가 작성한 **설계 문서**이다. FS 안의 ABAP 예시·snippet은 **설명·의사코드**일 수 있으며 고객 첨부본과 **동일하지 않다**고 가정한다.
- 네가 출력하는 `# 납품 ABAP 초안`만이 이 단계의 **공식 납품 코드 초안**이다.

### RFP 요약
{rfp_ctx}
{lib_for}

### 고객 참고 ABAP (요청 제출 시 첨부 — **납품 결과 아님**, 패턴·인터페이스 힌트로만 활용)
{ref_for_prompt}

### 인터뷰 발췌
{conv_snip}

### 제안서 발췌 (UI 힌트용, FS 미기재 필드 보완만)
{prop_snip}

### 기능명세서 (본문) — 구현 근거
{fs_block}

{_ms}

**프로그램명**:
{(f"고객이 지정한 프로그램 ID **`{cust_pid}`** 로 `REPORT {cust_pid}.` 를 시작한다.") if cust_pid else "RFP에 프로그램 ID가 없다. FS·요청 제목에 맞춰 **합리적인 Z/Y REPORT명**을 하나 정하고 그 이름으로 프로그램 전체를 작성한다."}
**T-Code**: 고객 지정값이 `{tcode or "(없음)"}` 일 때만 주석으로 언급. 없으면 임의 T-Code를 만들지 말 것.

출력 형식 (**반드시 준수**):
1. 첫 줄: `# 납품 ABAP 초안`
2. 짧은 설명 단락 (한국어)
3. `## ABAP 소스` 다음에 **단일** fenced code block, 언어 태그 `abap`. 그 안에 전체 프로그램.
4. 선택적으로 `## 구현 메모`: 미결정 테이블·RFC·테스트 필요 항목

ABAP 작성 규칙:
- 7.40+ 구문 가정 가능. 변수는 DATA/FIELD-SYMBOLS 명확히.
- 선택화면 필요 시 PARAMETERS/SELECT-OPTIONS.
- 리스트 결과는 초기 버전이라도 LOOP/WRITE 또는 cl_salv_table 수준 중 하나를 택해 **실행 흐름이 보이게**.
- 존재가 불명확한 테이블·함수 호출 금지; 대신 주석 `-- TODO: DDIC/인터페이스 검증`.
""",
        agent=abap_agent,
        expected_output="마크다운: 제목 + abap 코드 펜스 + 메모",
    )

    review_agent = Agent(
        role="SAP ABAP 코드 검수자",
        goal="FS·요구와 맞는지 ABAP 초안을 점검하고 안전하게 다듬는다",
        backstory="""당신은 시니어 ABAP 리뷰어로 정적 분석·네이밍·구문 호환성을 감사한다.
고객 FS와 모순되는 동작, 위험한 DDIC 추정, 7.40+ 구문 오류 가능성을 찾아 fenced ABAP 블록을 직접 수정한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    test_scenario_agent = Agent(
        role="SAP ABAP 테스트 설계자",
        goal="납품 ABAP에 대한 실행·회귀 테스트 시나리오를 구체적으로 작성한다",
        backstory="""기능·경계·오류 경로를 표로 정리하고, 재현 가능한 단계와 기대 결과를 한국어로 적는다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    _ph(f"{agent_label_ko('p_coder')} — Gemini({get_gemini_model_id()}) 호출 시작 · 수 분 걸릴 수 있음")
    crew_k = Crew(
        agents=[abap_agent],
        tasks=[kevin_task],
        process=Process.sequential,
        verbose=False,
    )
    out_k = str(crew_k.kickoff()).strip()
    _ph(f"{agent_label_ko('p_coder')} 단계 완료 · 출력 길이 약 {len(out_k)}자")

    young_task = Task(
        description=(
            "### 입력 — ABAP 초안 마크다운\n\n"
            + _tail_for_followup_prompt(out_k)
            + """

### 검수 지시
위 마크다운 전체를 ABAP 코드 검수자 관점에서 검토하라.

`# 납품 ABAP 초안` 제목과 본문 구조를 유지한다. `## ABAP 소스` 아래에는 **단일** `abap` fenced 블록만 둔다.
`## 코드 검수 요약`에 5~12문장으로 핵심 변경·잔여 리스크를 적고, 필요 시 ABAP 펜스 내부를 직접 고친다.

출력: 이전 초안을 대체하는 **완결된 단일 마크다운** (검수 반영본)."""
        ),
        agent=review_agent,
        expected_output="검수 반영 마크다운 전체",
    )

    _ph(f"{agent_label_ko('p_inspector')} — Gemini 호출 시작")
    crew_y = Crew(
        agents=[review_agent],
        tasks=[young_task],
        process=Process.sequential,
        verbose=False,
    )
    out_y = str(crew_y.kickoff()).strip()
    _ph(f"{agent_label_ko('p_inspector')} 단계 완료 · 출력 길이 약 {len(out_y)}자")

    brian_task = Task(
        description=(
            "### 입력 — 코드 검수 반영 마크다운\n\n"
            + _tail_for_followup_prompt(out_y)
            + """

### 테스트 섹션 추가 지시
위 마크다운 전체 본문을 손대지 않고 유지한 채, 문서 **맨 아래**에
`## 테스트 시나리오` 섹션만 추가하라.
케이스 ID, 목적, 사전 조건, 단계, 기대 결과를 마크다운 표로 작성한다.

출력: 이전 모든 섹션 + 테스트 섹션이 포함된 **하나의** 마크다운."""
        ),
        agent=test_scenario_agent,
        expected_output="테스트 시나리오까지 포함한 최종 마크다운",
    )

    _ph(f"{agent_label_ko('p_tester')} — Gemini 호출 시작")
    crew_b = Crew(
        agents=[test_scenario_agent],
        tasks=[brian_task],
        process=Process.sequential,
        verbose=False,
    )
    out_b = str(crew_b.kickoff()).strip()
    _ph(f"{agent_label_ko('p_tester')} 단계 완료 · 최종 길이 약 {len(out_b)}자")
    return out_b
