"""
Paid Tier — FS·납품 ABAP

- FS: CrewAI / Gemini (대외명 「FS설계」 에이전트, 내부 role p_architect). 키 없으면 예외만(가짜 문서 없음).
- 납품 ABAP(권장): JSON 슬롯(코더→검수) + 구현·운영 가이드 마크다운 + 테스트 시나리오 마크다운.
  JSON 실패 시 레거시 단일 마크다운(ABAP 펜스 + 말미 테스트)으로 폴백한다. 키 필수.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from ..agent_playbook import playbook_prompt_wrap
from .free_crew import (
    _MEMBER_FACING_NO_STORAGE_NAMES,
    _fmt_conv,
    _fmt_rfp,
    _get_llm,
    _lib_block_heading,
    _parse_code_library_context,
)
from ..agent_display import agent_label_ko
from ..delivered_code_package import (
    extract_json_object_from_llm_text,
    legacy_markdown_from_package,
    merge_slots_json_with_extras,
    sanitize_test_scenarios_markdown,
    delivered_package_has_body,
)
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
    playbook_addon: str = "",
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
    _pb_fs = playbook_prompt_wrap(playbook_addon)

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
{_pb_fs}""",
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


def _monolithic_delivered_abap_markdown(
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
    레거시: 단일 마크다운(ABAP 펜스 + 말미 테스트 시나리오).
    JSON 패키지 파싱 실패 시 폴백으로만 사용한다.
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
FS 본문에 **컨설턴트 FS 첨부**와 **에이전트 생성 FS**가 함께 있으면 **컨설턴트 첨부를 최우선**으로 따르고, 에이전트 FS는 보조 참고로만 사용한다.

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


def generate_delivered_abap_artifact(
    rfp_data: dict[str, Any],
    fs_text: str,
    proposal_text: str,
    conversation: list[dict],
    *,
    code_library_context: str = "",
    member_safe_output: bool = False,
    phase_log: Callable[[str], None] | None = None,
    playbook_addon: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """
    권장: JSON 슬롯 패키지 + 별도 구현 가이드 + 테스트 시나리오 마크다운.
    JSON 단계가 실패하면 레거시 단일 마크다운으로 폴백하고 (None, markdown)을 반환한다.
    """
    llm = _get_llm()

    def _ph(msg: str) -> None:
        if phase_log:
            phase_log(msg)

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
    cust_pid = (rfp_data.get("program_id") or "").strip()
    tcode = (rfp_data.get("transaction_code") or "").strip()

    json_coder = Agent(
        role="SAP ABAP 시니어 개발자",
        goal="FS에 맞춰 INCLUDE 슬롯 구조의 ABAP를 JSON으로보낸다",
        backstory="""15년차 ABAP 개발자. Report/INCLUDE/화면 PBO·PAI를 분리해 납품한다.
출력은 **유효한 JSON 한 덩어리**만 허용된다. 테스트 시나리오는 JSON에 넣지 않는다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    json_reviewer = Agent(
        role="SAP ABAP 코드 검수자",
        goal="JSON 패키지의 구문·스키마·ABAP 내용을 검수한다",
        backstory="""정적 분석·네이밍·7.40+ 호환을 점검하고, JSON 문자열 이스케이프가 깨지지 않게 수정한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    guide_agent = Agent(
        role="SAP 구현·운영 컨설턴트",
        goal="납품 코드 패키지에 대한 구현·운영 가이드를 한국어 마크다운으로 쓴다",
        backstory="""전환·권한·배포·운영 점검·의존성을 실무 관점에서 정리한다. 소스 전체를 반복 붙여넣지 않는다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    test_agent = Agent(
        role="SAP ABAP 테스트 설계자",
        goal="실행·회귀 테스트 시나리오를 한국어 마크다운으로 작성한다",
        backstory="""경계·오류 경로를 표로 정리한다. 과도한 표 구분선(---) 남발은 피한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    pid_rule = (
        (f"고객 지정 프로그램 ID **`{cust_pid}`** — JSON `program_id`에 동일하게 넣고, main_report 슬롯의 REPORT/PROGRAM이 이 이름을 따른다.")
        if cust_pid
        else "RFP에 프로그램 ID가 없다. 합리적인 Z/Y 이름을 정해 `program_id`와 슬롯 소스에 일관되게 쓴다."
    )
    tcode_rule = f"T-Code 고객 지정: `{tcode or '(없음)'}` — 없으면 임의 T-Code를 만들지 말 것."
    _pb_del = playbook_prompt_wrap(playbook_addon)

    slot_task = Task(
        description=f"""기능명세서(FS)를 구현 근거로 삼아 **납품 ABAP 패키지**를 JSON으로만 출력하라.
RFP·인터뷰·제안서는 FS와 충돌 시 **FS 우선**이다.

**역할 구분:**
- 고객 참고 ABAP: 요청 시 첨부한 **원본**이며 납품물이 아니다. 패턴 힌트로만 사용.
- FS 내 예시 코드는 설명용일 수 있다.

### RFP
{rfp_ctx}
{lib_for}

### 고객 참고 ABAP
{ref_for_prompt}

### 인터뷰 발췌
{conv_snip}

### 제안서 발췌
{prop_snip}

### 기능명세서(FS)
{fs_block}

{_ms}

**식별자:** {pid_rule}
**{tcode_rule}**

출력: **JSON 한 개만** (앞뒤 설명 문장 금지). 선택적으로 ```json 펜스 허용.

스키마:
{{
  "program_id": "Z...",
  "slots": [
    {{
      "role": "main_report",
      "filename": "zxxx_main.prog.abap",
      "title_ko": "메인 리포트",
      "source": "REPORT zxxx.\\n..."
    }}
  ],
  "coder_notes": "미결 DDIC·RFC 등"
}}

`slots` 규칙:
- `role`은 반드시 다음 중 하나: main_report, include, top, pbo, pai, forms, screen, other
- **반드시** `role`이 `main_report`인 슬롯을 1개 이상 포함하고, 그 `source`에 실행 가능한 REPORT/프로그램 골격을 둔다.
- INCLUDE·TOP·PBO/PAI·서브루틴은 **별도 슬롯**으로 나누는 것을 우선한다(단일 거대 파일 지양).
- `filename`: 영문·숫자·언더스코어·점만, 확장자 `.abap` 권장.
- ABAP 문자열 내 따옴표는 JSON 이스케이프를 반드시 지킨다.
- **테스트 시나리오·구현 가이드는 JSON에 넣지 않는다.**
{_pb_del}""",
        agent=json_coder,
        expected_output="유효한 JSON 한 덩어리",
    )

    _ph(f"{agent_label_ko('p_coder')} — JSON 슬롯 패키지 Gemini({get_gemini_model_id()}) 호출 시작")
    crew_slots = Crew(
        agents=[json_coder],
        tasks=[slot_task],
        process=Process.sequential,
        verbose=False,
    )
    out_slots = str(crew_slots.kickoff()).strip()
    _ph(f"{agent_label_ko('p_coder')} JSON 초안 완료 · 약 {len(out_slots)}자")

    review_task = Task(
        description=(
            "### 입력 JSON/텍스트 (ABAP 패키지 초안)\n\n"
            + _tail_for_followup_prompt(out_slots, max_chars=118_000)
            + """

### 검수
1. `json.loads`로 파싱 가능한 **순수 JSON 객체 하나**만 출력한다 (설명 문장 없음).
2. 스키마: program_id, slots[], coder_notes(선택).
3. 각 slot: role, filename, title_ko, source (문자열).
4. main_report 슬롯이 있고 source에 REPORT/프로그램 본문이 있어야 한다.
5. ABAP 내 줄바꿈은 JSON 문자열 안에서 \\n 이스케이프로 표현한다.
"""
        ),
        agent=json_reviewer,
        expected_output="파싱 가능한 JSON 한 덩어리",
    )
    _ph(f"{agent_label_ko('p_inspector')} — JSON 검수 Gemini 호출 시작")
    crew_rev = Crew(
        agents=[json_reviewer],
        tasks=[review_task],
        process=Process.sequential,
        verbose=False,
    )
    out_rev = str(crew_rev.kickoff()).strip()
    _ph(f"{agent_label_ko('p_inspector')} JSON 검수 완료 · 약 {len(out_rev)}자")

    data = extract_json_object_from_llm_text(out_rev)
    if not data:
        _ph("JSON 파싱 실패 — 레거시 단일 마크다운 파이프라인으로 폴백")
        return None, _monolithic_delivered_abap_markdown(
            rfp_data,
            fs_text,
            proposal_text,
            conversation,
            code_library_context=code_library_context,
            member_safe_output=member_safe_output,
            phase_log=phase_log,
        )

    if cust_pid and not (str(data.get("program_id") or "").strip()):
        data["program_id"] = cust_pid

    slots_summary = _tail_for_followup_prompt(json.dumps(data, ensure_ascii=False), max_chars=96_000)

    guide_task = Task(
        description=f"""아래 FS 발췌와 **납품 ABAP 패키지 JSON**(slots 소스 포함)을 읽고,
운영·이행 담당자를 위한 **구현·운영 가이드**만 작성하라.

### FS (발췌)
{_truncate(fs_block, 72_000)}

### 패키지 JSON
{slots_summary}

출력: **마크다운 본문만**. 첫 제목은 `# 구현·운영 가이드` 로 시작.
내용: 배포/트랜스포트, 권한·역할, 데이터 이관, 운영 모니터링, 알려진 제한, 고객 확인 사항.
각 슬롯 파일명을 참조할 수 있으나 ABAP 소스 전체를 반복하지 마라.
{_ms}
""",
        agent=guide_agent,
        expected_output="구현·운영 가이드 마크다운",
    )
    _ph("구현·운영 가이드 생성 — Gemini 호출")
    crew_g = Crew(
        agents=[guide_agent],
        tasks=[guide_task],
        process=Process.sequential,
        verbose=False,
    )
    guide_md = str(crew_g.kickoff()).strip()
    _ph("구현·운영 가이드 완료")

    test_task = Task(
        description=f"""아래 FS 발췌와 납품 패키지 JSON(slots)을 바탕으로 **테스트 시나리오**만 작성하라.

### FS (발췌)
{_truncate(fs_block, 56_000)}

### 패키지 JSON
{slots_summary}

출력: **마크다운 본문만**. 첫 제목은 `# 테스트 시나리오` 로 시작.
케이스 ID, 목적, 사전 조건, 단계, 기대 결과를 **하나의 마크다운 표**로 정리한다 (최대 18행).
표 위아래로 `---` 구분선을 연속 나열하지 마라.
{_ms}
""",
        agent=test_agent,
        expected_output="테스트 시나리오 마크다운",
    )
    _ph(f"{agent_label_ko('p_tester')} — 테스트 시나리오 Gemini 호출 시작")
    crew_t = Crew(
        agents=[test_agent],
        tasks=[test_task],
        process=Process.sequential,
        verbose=False,
    )
    test_md = sanitize_test_scenarios_markdown(str(crew_t.kickoff()).strip())
    _ph(f"{agent_label_ko('p_tester')} 테스트 시나리오 완료")

    pkg = merge_slots_json_with_extras(
        data,
        implementation_guide_md=guide_md,
        test_scenarios_md=test_md,
    )
    if not pkg or not delivered_package_has_body(pkg):
        _ph("패키지 정규화 후 ABAP 본문 없음 — 레거시 파이프라인으로 폴백")
        return None, _monolithic_delivered_abap_markdown(
            rfp_data,
            fs_text,
            proposal_text,
            conversation,
            code_library_context=code_library_context,
            member_safe_output=member_safe_output,
            phase_log=phase_log,
        )

    return pkg, legacy_markdown_from_package(pkg)


def generate_delivered_abap_markdown(
    rfp_data: dict[str, Any],
    fs_text: str,
    proposal_text: str,
    conversation: list[dict],
    *,
    code_library_context: str = "",
    member_safe_output: bool = False,
    phase_log: Callable[[str], None] | None = None,
    playbook_addon: str = "",
) -> str:
    """하위 호환: 최종 레거시 마크다운 문자열만 필요할 때."""
    _pkg, md = generate_delivered_abap_artifact(
        rfp_data,
        fs_text,
        proposal_text,
        conversation,
        code_library_context=code_library_context,
        member_safe_output=member_safe_output,
        phase_log=phase_log,
        playbook_addon=playbook_addon,
    )
    return md
