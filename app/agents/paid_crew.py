"""
Paid Tier — FS·납품 ABAP

FS: David 에이전트가 RFP·인터뷰·제안서(참고)·코드 맥락을 검토해 상세 기능명세(Markdown) 작성.
납품 코드: 1차 스텁(추후 Kevin/LLM 연동).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from .free_crew import (
    _MEMBER_FACING_NO_STORAGE_NAMES,
    _fmt_conv,
    _fmt_rfp,
    _get_llm,
    _lib_block_heading,
    _member_abap_block,
    _parse_code_library_context,
)
from ..gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def _truncate(s: str, max_len: int) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + f"\n\n…(이하 약 {len(t) - max_len}자 생략)"


def _fs_no_llm_fallback(rfp_data: dict[str, Any], proposal_text: str) -> str:
    """API 키 없을 때 — Proposal 전문 복붙 금지, 안내·최소 메타만."""
    rfp_ctx = _fmt_rfp(rfp_data)
    prop_snip = _truncate(proposal_text, 1800)
    return f"""# 기능명세서 (FS)

> **자동 생성 생략**: `GOOGLE_API_KEY`(또는 Crew가 사용하는 Gemini 키)가 설정되지 않아 LLM FS를 만들 수 없습니다.
> Railway/로컬 환경에 키를 넣은 뒤 관리자 화면에서 **FS 생성 시작**을 다시 실행하세요.
> (현재 문서는 FS **본문이 아닙니다**.)

## RFP 메타 (입력 데이터 요약)

{rfp_ctx}

## Development Proposal 발췌 (참고용·FS 아님)

{prop_snip if prop_snip else "(제안서 없음)"}

---
*generated_by=paid_crew_fallback_no_llm*
"""


def generate_fs_markdown(
    rfp_data: dict[str, Any],
    conversation: list[dict],
    proposal_text: str,
    *,
    code_library_context: str = "",
    member_safe_output: bool = False,
) -> str:
    """
    David(FS 설계): 요구(RFP)·질의응답(인터뷰)·제안서(고객안)를 교차 검토해 **상세 FS**를 마크다운으로 작성.
    제안서 문단을 그대로 복사하지 않도록 프롬프트에서 금지한다.
    """
    if not (os.environ.get("GOOGLE_API_KEY") or "").strip():
        return _fs_no_llm_fallback(rfp_data, proposal_text)

    llm = _get_llm()
    david = Agent(
        role="SAP 기능명세(FS)·상세설계 책임자",
        goal="요구분석·인터뷰·제안서를 교차검증하고 개발 착수 가능한 상세 기능명세를 만든다",
        backstory="""당신은 David입니다. 대형 ERP SI에서 FS/상세설계를 수십 건 작성한 리드 컨설턴트다.
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
    ref_block = _member_abap_block(member_ref)
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
        description=f"""아래 (1)(2)(3)을 **모두** 읽고 교차검증하라. 서로 모순되면 FS 끝에 **오픈 이슈**로 적시하라.

### (1) RFP 원천 요구
{rfp_ctx}
{lib_for}{ref_block}

### (2) 인터뷰 — 질의·고객 답변 전체
{conv_ctx}

### (3) 이미 발행된 Development Proposal (고객안)
이 문서는 **맥락 정렬·누락 점검용**이다.
**절대 요약이나 표·문장을 그대로 복사해 FS에 붙이지 마라.** FS는 설계 산출물로 **새로 작성**한다.

{prop_block}

{_ms}
{id_rules}

**모델**: 설계 시 내부적으로 `{get_gemini_model_id()}` 계열을 사용 중임을 알고, 불명확한 SAP 전제는 오픈 이슈로 남겨라.

출력: **단일 마크다운** 문서. 첫 제목 줄은 반드시 `# 기능명세서 (FS)` 로 시작.

권장 목차(### 수준 소제목으로 채워라 — Proposal의 '개발 개요' 같은 고객용 구조를 그대로 베끼지 말 것):
### 1. 목적·범위·전제
### 2. 용어
### 3. 업무 프로세스·후속 트랜잭션 연계
### 4. 프로그램·진입점 (유형: Report / ALV / Dialog 등)
### 5. 화면 명세 — **필드 단위 마크다운 표** (필드명, 필수여부, F4, 참조테이블/도메인 추정 시 기재)
### 6. 선택화면·variant·초기값
### 7. 조회·저장·업무 검증 규칙·메시지
### 8. 권한·통제
### 9. 인터페이스 / RFC·BAPI·배치 (해당 시, 없으면 근거와 함께 '해당 없음')
### 10. 예외·에러·로그
### 11. 데이터량·성능 가정
### 12. 테스트 포인트(단위·통합 관점 체크리스트)
### 13. 오픈 이슈·고객 확인 필요 (출처: RFP/인터뷰 라운드/Proposal 중 어디와 불일치인지 명시)

규칙:
- 고객 설득용 마케팅 문장 금지.
- Proposal·인터뷰가 말하지 않은 SAP 세부사항은 **추정**이라면 반드시 "가정:"으로 표시.
""",
        agent=david,
        expected_output="완결된 기능명세서 마크다운 본문",
    )

    crew = Crew(
        agents=[david],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
    return str(crew.kickoff()).strip()


def generate_delivered_abap_markdown(rfp_summary: dict[str, Any], fs_text: str) -> str:
    """납품 ABAP를 Markdown 코드 블록으로 (스텁·추후 Kevin 연동)."""
    title = rfp_summary.get("title") or ""
    prog = rfp_summary.get("program_id") or "Z_STUB_REPORT"
    fs_excerpt = (fs_text or "").strip()[:4000]
    return f"""# Delivered ABAP (스텁)

RFP **{title}** — 프로그램 ID 예시: `{prog}`

## ABAP 소스 (스텁 — 유료 코드 에이전트 연결 전)

```abap
*&---------------------------------------------------------------------*
*& TODO: 기능명세서(David 산출) 기반으로 Kevin 에이전트가 채운다.
REPORT {prog}.

WRITE: / 'Stub ABAP placeholder — regenerate after FS is finalized'.

*&---------------------------------------------------------------------*
```

## FS 발췌 (참조)

{fs_excerpt}

---
*generated_by=paid_crew_stub_kevin_pending*
"""
