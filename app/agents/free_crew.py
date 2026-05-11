"""
Free Tier Crew – SAP Dev Hub

에이전트 구성:
  f_questioner  (Mia)   – 전 라운드 인터뷰 질문 생성 전담
  f_analyst     (Hannah)– 전 라운드 답변 분석 전담
  f_writer      (Jun)   – Development Proposal 작성
  f_reviewer    (Sara)  – Proposal 품질 검토 및 최종 승인

플로우:
  [라운드 질문 생성] f_analyst → f_questioner → (선택) 요구분석 합불 + 질의 1회 재작성 + f_reviewer 최종(INTERVIEW_QA_ENHANCE, 기본 on)
  [Proposal 생성]   f_analyst → f_writer → f_reviewer (인터뷰 완료 후 1회 호출)
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from crewai import Agent, Task, Crew, Process, LLM
from dotenv import load_dotenv

from ..agent_playbook import playbook_prompt_wrap
from ..agent_display import agent_label_ko, agents_ai_source_ko
from ..gemini_model import get_gemini_model_id
from ..rfp_reference_code import REF_SLOT_MARKER

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MAX_ROUNDS = 3
MAX_SUGGESTED_ANSWERS = 5
# 한 인터뷰 라운드당 질문 개수 상한(조기 완료 시 그 전에 끊김)
MAX_QUESTIONS_PER_ROUND = 3


def _interview_qa_enhance_enabled() -> bool:
    """false/0/off 이 아니면 인터뷰 질+선지 품질 파이프라인 사용."""
    v = (os.environ.get("INTERVIEW_QA_ENHANCE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _parse_analyst_gate_json(raw: str) -> tuple[bool, str]:
    s = (raw or "").strip()
    if not s:
        return True, ""
    src = s
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            src = m.group(1).strip()
    try:
        j = json.loads(src)
        if isinstance(j, dict):
            p = j.get("pass", True)
            if isinstance(p, str):
                p = p.lower() in ("true", "1", "yes")
            issues = (j.get("issues") or "").strip()
            return bool(p), issues[:2500]
    except Exception:
        pass
    return True, ""


def run_interview_qa_enhancement(
    llm: LLM,
    rfp_data: dict,
    conversation: list[dict],
    round_num: int,
    step_label: str,
    in_round_qa: Optional[list[tuple[str, str]]],
    code_library_context: str,
    question: str,
    suggested_answers: list,
) -> tuple[str, list[str]]:
    """
    B: 요구분석 합불 → 불합이면 질의 1회 재작성 → A: 제안검수 최종(질문·선지 전면 대체 가능).
    """
    q0 = (question or "").strip()
    sa0 = _normalize_suggested_answers(list(suggested_answers or []))
    if not _interview_qa_enhance_enabled() or not q0:
        return q0, sa0

    f_analyst, f_questioner, _, f_reviewer = _make_agents(llm)
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)
    if len(conv_ctx) > 6000:
        conv_ctx = conv_ctx[:6000] + "\n…(생략)"
    inr = (
        _fmt_in_round(in_round_qa)
        if in_round_qa
        else "(이번 라운드 첫 질문 — 아직 답 없음)"
    )
    lib_snip = ""
    if code_library_context:
        summ, _ = _parse_code_library_context(code_library_context)
        if summ:
            lib_snip = f"\n[유사 코드 요약 일부]\n{summ[:1500]}\n"

    q, sa = q0, sa0
    sa_lines = "\n".join(f"- {x}" for x in sa[:MAX_SUGGESTED_ANSWERS]) or "(없음)"

    gate_task = Task(
        description=f"""당신은 SAP 요구분석 담당이다. 아래 **후보 인터뷰 질문 1개**와 **선택 답안**이
이 RFP와 인터뷰 맥락에 맞는지 **엄격히** 판정하라.

[라운드 {round_num}] · {step_label}

[RFP]
{rfp_ctx}

[이전까지 인터뷰]
{conv_ctx}

[이번 라운드]
{inr}
{lib_snip}

[후보 질문]
{q}

[후보 선택 답안]
{sa_lines}

판정 (하나라도 심각하면 pass=false):
- **한 질문=한 가지**인가? (또는 질문·선에 **둘 이상 주제**가 섞이면 불합. 한 선지에 둘 이상 끼인 경우도 마찬가지)
- RFP·이전 Q&A에 **이미 확답**한 취지를 **다시 묻는가**? (그렇다면 불합)
- RFP에 애매한 **한국어/업말**이 있을 때 임의로 "Delivery category" 등 **틀릴 수 있는** 영어/SAP 풀어쓰기로 덮지 않고 **뜻을 묻는**가? (아니라면 불합. Schedule line category 와 'Delivery category' 를 혼동·동치하지 말라.)
- 2~{MAX_SUGGESTED_ANSWERS}개, 각 **한 요지**의 완성 답

출력 JSON 한 블록만:
{{"pass": true 또는 false, "issues": "불합이면 질문 작성자가 고칠 점(한국어). 합격이면 빈 문자열."}}""",
        agent=f_analyst,
        expected_output='{"pass": ..., "issues": "..."}',
    )
    try:
        gate_crew = Crew(
            agents=[f_analyst],
            tasks=[gate_task],
            process=Process.sequential,
            verbose=False,
        )
        ok, issues = _parse_analyst_gate_json(str(gate_crew.kickoff()))
    except Exception:
        ok, issues = True, ""

    if not ok and issues.strip():
        retry_task = Task(
            description=f"""아래 **검토 사유**를 반드시 반영해 인터뷰 질문 1개와 suggested_answers 를 **다시** 작성하라.

[검토 사유]
{issues}

[참고용 이전 후보(필요 시 전면 폐기)]
질문: {q}
답안:
{sa_lines}

[RFP]
{rfp_ctx[:4000]}

[이번 라운드]
{inr}

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}

출력 JSON 한 블록만:
{{"question": "...", "suggested_answers": ["...", "..."]}} (2~{MAX_SUGGESTED_ANSWERS}개)""",
            agent=f_questioner,
            expected_output="JSON",
        )
        try:
            rc = Crew(
                agents=[f_questioner],
                tasks=[retry_task],
                process=Process.sequential,
                verbose=False,
            )
            rq, rsa = _parse_question_and_suggestions(str(rc.kickoff()))
            if rq:
                q, sa = rq, _normalize_suggested_answers(rsa)
                if len(sa) < 2:
                    more = generate_suggested_answers_for_question(
                        rfp_data, q, round_num, 1
                    )
                    sa = _normalize_suggested_answers(list(sa) + list(more))
        except Exception:
            pass

    sa_lines2 = "\n".join(f"- {x}" for x in sa[:MAX_SUGGESTED_ANSWERS]) or "(없음)"
    rev_task = Task(
        description=f"""당신은 제안서·인터뷰 품질 검수자다. 아래 **인터뷰 질문·선택 답안 세트**를 최종 확정하라.

**질문 핵심이 틀렸다면 질문을 완전히 바꿔도 된다.** 한 턴에 **한 가지**만(합친 질문이면 쪼개기). **질문**은 짧게, **선지에 쓰일 예시**를 질문에 **중복**하지 말라.

[RFP 핵심]
{rfp_ctx[:3500]}

[인터뷰 맥락 일부]
{conv_ctx[:3500]}

[이번 라운드]
{inr}

[현재 세트]
질문: {q}
선택 답안:
{sa_lines2}

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}

- 고객(IT 비전문가)이 읽을 수 있는 한국어, SAP 용어는 앞서 규칙 따름
- suggested_answers 는 2~{MAX_SUGGESTED_ANSWERS}개, 복수 선택 가능한 완성 답

출력 JSON 한 블록만:
{{"question": "...", "suggested_answers": ["...", "..."]}}""",
        agent=f_reviewer,
        expected_output="JSON",
    )
    try:
        rev_crew = Crew(
            agents=[f_reviewer],
            tasks=[rev_task],
            process=Process.sequential,
            verbose=False,
        )
        fq, fsa = _parse_question_and_suggestions(str(rev_crew.kickoff()))
        if fq:
            if len(fsa) < 2:
                more = generate_suggested_answers_for_question(
                    rfp_data, fq, round_num, 1
                )
                fsa = _normalize_suggested_answers(list(fsa) + list(more))
            return fq[:2000], fsa
    except Exception:
        pass
    if len(sa) < 2 and q:
        more = generate_suggested_answers_for_question(
            rfp_data, q, round_num, 1
        )
        sa = _normalize_suggested_answers(list(sa) + list(more))
    return q, sa


def _interview_source_after_enhance() -> str:
    return agents_ai_source_ko("f_analyst", "f_questioner", "f_reviewer")

# Mia 인터뷰: RFP 범위·SAP 용어·답안 버튼 일관성
MIA_INTERVIEW_SCOPE_AND_STYLE = """
[질문 범위 — 반드시 준수]
- RFP 본문·첨부·이전 인터뷰 답에 없는 편의 기능·부가 UX는 질문에 넣지 마라. (RFP에 명시된 경우만 예외.)
- **한 턴에 정하는 것은 '한 가지 질문'뿐이다.** '또한/그리고'로 Plant와 Sales Order Type처럼 **주제가 다른** 것을 한 질문에 섞지 마라 — 반드시 **질문을 나눈다.**
- 질문은 **짧고** (2~3문장 이하). **선지(suggested_answers)에 쓰일 나열·시나리오**를 질문에 **미리 중복**해서 길게 쓰지 마라. (옵션이 말하도록 하고, 질문은 한 축의 결정만.)
- [전체 인터뷰 + 이번 라운드 Q&A]에 **이미 확답**한 주제(같은 말의 다른 말로 포함)는 **다시 묻지 마라.**

[RFP·애매한 표현 — 임의 번역·영어 갖다 붙이기 금지]
- RFP에 '납기 카테고리' 등 **뜻이 불명확**한 말이 있고 정의가 없을 때, 임의로 "Delivery category" 등으로 **끼워 맞추지 말고** RFP 식 **그대로** 인용한 뒤, **한 가지 확인 질문**으로 "무엇을 뜻하는지(예: Schedule line category(일정 라인)인지, 다른 항목인지)"를 묻는다.
- Schedule line category(Einteilungskategorie)는 SAP 표준 용어이나, "Delivery category"는 **이 맥락의 직역**이 아닐 수 있음(혼동 금지). **잘못 맞을 바엔** 고객에게 뜻을 묻는다.

[suggested_answers — 한 줄씩, 한 질문에 대해서만]
- 2~5개. **각 항목은 '위에 묻는 한 질문'에 대한 응답만** (한 항목에 **서로 독립된** 두 가지를 합쳐 쓰지 말 것).
- 서로 **다른 대안**이면 OK, 복수 선택이 의미가 있으면 OK. (단, **한 행=한 요지**.)
- **과장되게 정중한 백서체·다단 영어 병기**는 피하고, 실무 톤으로 짧게.

[출력 형식]
- JSON에서 ** … ** 별표 감싸기 금지.
"""

SAP_INTERVIEW_CREDIBILITY = """
[SAP 사실·질문 품질 — 반드시 준수]
- BAPI/트랜잭션 필수 키를 "자동/수동 선택하시죠"식 **템플릿**으로만 묻지 마라. **이전 답·RFP에 이미 정책이 있으면** 그 취지를 따르고 **같은 주제는 반복하지 않는다.**
- "필드가 있나", "마스터 조회하나"만 나열한 **상투** 질문/선지는 금지. RFP·도메인에 **특정**한 정책·실패/재처리·경계만.
- RFP·이전 답이 충분하면 followup JSON에서 **round_complete: true** (억지로 3문항을 채우지 않는다. 한 라운드 최대 3문항).
"""

_MEMBER_FACING_NO_STORAGE_NAMES = """
[고객 서면 필수 — 일반 회원 RFP]
생성하는 질문·제안서·요약 등 **고객에게 보이는 모든 문장**에
'코드 라이브러리', '서버 라이브러리', '내부 코드 DB', 'Code Library' 등 **내부 코드 보관함을 특정하는 표현을 넣지 마라.**
내부 패턴을 언급할 때는 '유사 구현 사례', '이전에 다룬 유사 흐름'처럼 중립적으로만 쓴다.
"""


def _lib_block_heading(member_safe_output: bool) -> str:
    if member_safe_output:
        return "[내부 유사 구현 사례 요약 — 모델 내부용; 고객 문서에 이 제목·저장소 명칭을 인용하지 마세요]"
    return "[서버 코드 라이브러리 – 유사 프로그램 요약 (고객 PC 로컬 ABAP 코드와 별개, 패턴 파악용)]"


def _member_abap_block(member_ref: str) -> str:
    """회원이 RFP **제출 시** 참고로 넣은 ABAP — FS·납품 자동생성물과 혼동되지 않게 제목을 고정한다."""
    if not (member_ref or "").strip():
        return ""
    return f"""

### 고객 참고 ABAP (요청서 제출 시 첨부한 **원본** · FS·납품 코드 **자동생성 결과 아님**)
{member_ref}
"""


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
        goal="한 번에 '한 가지 비즈니스 결정'만 묻는 짧고 실무적인 인터뷰를 만든다",
        backstory="""당신은 Mia입니다. SAP SD/MM 등 요구사항 인터뷰를 수백 건 보았다.
질문은 **한 턴에 한 축(한 결정)만** — 합쳐 묻지 않는다. 선지(예시 답)는 그 질문에 대해서만, 한 행에 한 요지.
RFP·이전 답이 이미 정한 것은 **반복**하지 않는다. RFP에 애매한 말이 있으면 **임의 영어/SAP용어**로 끼워 맞추지 말고 **뜻을 확인**하는 질문을 쓴다.
길고 격식만 남은 문장(번역투)은 피한다. 반드시 JSON으로만.""",
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

def _workflow_origin_rfp_addendum(rfp: dict) -> str:
    """분석·연동 워크플로에서 생성된 RFP — 인터뷰·제안 에이전트가 선행 산출물과 역할을 혼동하지 않도록."""
    w = str(rfp.get("workflow_origin") or "direct").strip().lower()
    if w == "abap_analysis":
        return (
            "\n- 워크플로 출처: ABAP 분석·개선 단계에서 신규 개발(RFP)로 연결된 건입니다. "
            "요구사항 본문에 선행 분석·개선 요청 요약이 포함될 수 있으므로 같은 취지를 다시 묻지 말고, "
            "신규 개발 범위·검증·인터페이스·운영 조건 등 **아직 확정되지 않은 항목**만 보완하십시오."
        )
    if w == "integration":
        return (
            "\n- 워크플로 출처: 연동 요구 분석에서 신규 개발(RFP)로 연결된 건입니다. "
            "선행 인터뷰·분석·연동 개선 맥락이 본문에 반영될 수 있으니 연동 전제는 유지하되, "
            "RFP(신규·확대 개발) 관점에서 **비어 있는 결정**만 질문·명세에 반영하십시오."
        )
    if w == "integration_native":
        return (
            "\n- 워크플로: **연동 개발(비 ABAP)** 전용 파이프라인입니다. "
            "VBA·Python·배치·API·소규모 웹 등 **SAP 외부 구현**이 주된 범위입니다. "
            "Z/Y ABAP 프로그램·RFC·BAPI 내부 구현을 전제로 한 질문은 피하고, "
            "인터페이스·데이터 교환·보안·운영·오류 처리·배포 환경 등 **연동 관점**에서만 보완 질문을 만드십시오."
        )
    return ""


def _fmt_rfp(rfp: dict) -> str:
    modules = [_MODULE_LABELS.get(m, m) for m in rfp.get("sap_modules", [])]
    devtypes = [_DEVTYPE_LABELS.get(d, d) for d in rfp.get("dev_types", [])]
    pid = (rfp.get("program_id") or "").strip()
    tcode = (rfp.get("transaction_code") or "").strip()
    base = (
        f"- 요청 제목: {rfp.get('title', '(없음)')}\n"
        f"- SAP 모듈: {', '.join(modules) or '(미선택)'}\n"
        f"- 개발 유형: {', '.join(devtypes) or '(미선택)'}\n"
        f"- 고객이 지정한 프로그램 ID(있으면 이 이름/식별자로 확정): {pid or '(미입력·제안서에서 임의 Z/Y는 금지)'}\n"
        f"- 고객이 지정한 트랜잭션 코드(있으면 실행 경로는 이 코드로만): {tcode or '(미입력·제안서에서 임의 T-Code는 금지)'}\n"
        f"- 요구사항:\n{rfp.get('description', '(없음)')}"
    )
    return base + _workflow_origin_rfp_addendum(rfp)


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


def _fmt_in_round(in_round: list[tuple[str, str]]) -> str:
    if not in_round:
        return "(이번 라운드 아직 답이 없음)"
    lines = []
    for i, (q, a) in enumerate(in_round, 1):
        lines.append(f"  Q{i}. {q}\n  A{i}. {a}")
    return "\n".join(lines)


def _normalize_suggested_answers(items) -> list[str]:
    """중복 제거, 공백 제거, 최대 MAX_SUGGESTED_ANSWERS."""
    if not items:
        return []
    seen = set()
    out: list[str] = []
    for x in items:
        t = str(x).strip()
        if not t or len(t) > 500:
            continue
        k = t.lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= MAX_SUGGESTED_ANSWERS:
            break
    return out


def _parse_one_question(raw: str) -> str:
    q, _ = _parse_question_and_suggestions(raw)
    return q


def _parse_question_and_suggestions(raw: str) -> tuple[str, list[str]]:
    """크루 출력에서 question + suggested_answers(있으면) 추출."""
    s = (raw or "").strip()
    sugg: list[str] = []
    if not s:
        return "", []
    src = s
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            src = m.group(1).strip()
    try:
        j = json.loads(src)
        if isinstance(j, dict):
            q = (j.get("question") or "").strip()
            sa = j.get("suggested_answers")
            if isinstance(sa, list):
                sugg = _normalize_suggested_answers(sa)
            if q:
                return q[:2000], sugg
    except Exception:
        pass
    # 폴백: 질문만
    qonly = _parse_one_question_legacy_block(s)
    return qonly, sugg


def _parse_followup_result(raw: str) -> dict:
    """
    Mia 후속: round_complete, next_question, suggested_answers.
    하위호환: question 키만 있으면 next_question으로 승급, round_complete는 False.
    """
    out: dict = {"round_complete": False, "next_question": "", "suggested_answers": []}
    s = (raw or "").strip()
    if not s:
        return out
    src = s
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            src = m.group(1).strip()
    try:
        j = json.loads(src)
        if isinstance(j, dict):
            rc = j.get("round_complete")
            if isinstance(rc, str):
                rc = rc.lower() in ("true", "1", "yes")
            out["round_complete"] = bool(rc)
            nq = (j.get("next_question") or "").strip()
            if not nq and not out["round_complete"]:
                nq = (j.get("question") or "").strip()
            out["next_question"] = nq[:2000] if nq else ""
            sa = j.get("suggested_answers")
            if isinstance(sa, list):
                out["suggested_answers"] = _normalize_suggested_answers(sa)
            if out["round_complete"]:
                out["next_question"] = ""
            return out
    except Exception:
        pass
    # 레거시: question + suggested_answers
    nq, sugg = _parse_question_and_suggestions(raw)
    if nq:
        out["next_question"] = nq
    out["suggested_answers"] = sugg
    return out


def _parse_one_question_legacy_block(s: str) -> str:
    src = s
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            src = m.group(1).strip()
    try:
        j = json.loads(src)
        if isinstance(j, dict) and "question" in j:
            return (j.get("question") or "").strip()[:2000]
        if isinstance(j, list) and j:
            return str(j[0]).strip()[:2000]
    except Exception:
        pass
    m = re.search(r'"question"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
    if m:
        return m.group(1).replace('\\"', '"').strip()[:2000]
    for ln in s.splitlines():
        t = ln.strip()
        if len(t) > 20:
            return t[:2000]
    return s[:2000] if len(s) > 20 else ""


def generate_suggested_answers_for_question(
    rfp_data: dict,
    question: str,
    round_num: int,
    step_in_round: int,
) -> list[str]:
    """
    질문 1개에 대해 일반회원이 고를 수 있는 답안 후보(2~5개, 최대 MAX_SUGGESTED_ANSWERS).
    """
    q = (question or "").strip()
    if not q:
        return []
    try:
        llm = _get_llm()
        _, f_questioner, _, _ = _make_agents(llm)
        rfp_ctx = _fmt_rfp(rfp_data)
        t = Task(
            description=f"""다음은 SAP 맞춤개발 RFP 인터뷰 질문입니다. 비전문가가 버튼만 눌러 한 질문에 답하도록, 짧은 답안 후보만 만드세요.

[RFP 요약]
{rfp_ctx}

[인터뷰 질문]
{q}

(라운드 {round_num}, 이 라운드 {step_in_round}번째 질문)

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}

참고: 별표 둘로 감싼 강조(**)는 쓰지 말 것.

출력 규칙: 2개 이상 최대 {MAX_SUGGESTED_ANSWERS}개. **각 항목은 위 [인터뷰 질문] 하나에 대한 응답만** — 한 행에 **두 가지 주제**(예: Plant+Sales Order Type)를 합치지 마라. 항목마다 1문장(약 120자). "잘 모르겠다" 류는 최대 1개.

JSON만 출력:
{{"suggested_answers": ["...", "..."]}}""",
            agent=f_questioner,
            expected_output='{"suggested_answers": []}',
        )
        crew = Crew(agents=[f_questioner], tasks=[t], process=Process.sequential, verbose=False)
        raw = str(crew.kickoff())
        return _parse_suggested_answers_only(raw)
    except Exception:
        return []


def _parse_suggested_answers_only(raw: str) -> list[str]:
    """JSON 본문에서 suggested_answers 배열만 추출."""
    s = (raw or "").strip()
    if not s:
        return []
    blob = s
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            blob = m.group(1).strip()
    try:
        j = json.loads(blob)
        if isinstance(j, dict) and isinstance(j.get("suggested_answers"), list):
            return _normalize_suggested_answers(j["suggested_answers"])
    except Exception:
        pass
    return []


def generate_sequential_start(
    rfp_data: dict,
    conversation: list[dict],
    round_num: int,
    code_library_context: str = "",
    member_safe_output: bool = False,
    playbook_addon: str = "",
) -> dict:
    """
    라운드의 첫 질문 1개 + (1라운드·라이브러리) 나머지 질문 풀.
    Returns:
        {"questions": [Q1], "library_pool": [...], "suggested_answers": [...], "source": "..."}
    """
    analysis_summary, lib_ctx = _parse_code_library_context(code_library_context)
    member_ref = (rfp_data.get("reference_code_for_agents") or "").strip()

    if round_num == 1 and code_library_context and not member_ref:
        try:
            ctx = lib_ctx if lib_ctx else json.loads(code_library_context)
            qs = [str(q).strip() for q in (ctx.get("questions") or []) if str(q).strip()]
            if qs:
                rest = [q for q in qs[1:4] if q][:2]
                su = generate_suggested_answers_for_question(
                    rfp_data, qs[0], round_num, 1
                )
                q_out, su_out = qs[0], su
                out_src = ctx.get(
                    "source",
                    "내부 유사 사례 기반" if member_safe_output else "코드 라이브러리 기반",
                )
                if _interview_qa_enhance_enabled() and (q_out or "").strip():
                    try:
                        llm_lib = _get_llm()
                        q2, a2 = run_interview_qa_enhancement(
                            llm_lib,
                            rfp_data,
                            conversation,
                            round_num,
                            "codelib-start",
                            None,
                            code_library_context,
                            str(qs[0]),
                            su or [],
                        )
                        if q2 and str(q2).strip():
                            q_out, su_out, out_src = (
                                str(q2).strip(),
                                a2,
                                _interview_source_after_enhance(),
                            )
                    except Exception:
                        pass
                return {
                    "questions": [q_out],
                    "library_pool": rest,
                    "source": out_src,
                    "suggested_answers": su_out,
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

{_lib_block_heading(member_safe_output)}
{analysis_summary}
"""
    member_ref_block = _member_abap_block(member_ref)
    _ms_rule = _MEMBER_FACING_NO_STORAGE_NAMES if member_safe_output else ""
    _pb_wrap = playbook_prompt_wrap(playbook_addon)
    analyze_task = Task(
        description=f"""아래 RFP와 지금까지의 인터뷰 내용을 분석하세요.

[RFP 정보]
{rfp_ctx}

[인터뷰 내용]
{conv_ctx}
{lib_for_hannah}{member_ref_block}
[현재 라운드: {round_num} / 전체: {MAX_ROUNDS}]
{_ms_rule}

다음 항목을 간결하게 분석하세요:
1. 현재까지 파악된 핵심 요구사항 (2~3줄) — RFP·이전 답에 근거
2. 구현에 반드시 필요한 미확정 사항만 (편의·부가기능 제외)
3. 이번 라운드 첫 질문으로 물을 한 가지 결정(한 줄)

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}
※ 내부 유사 사례·회원 제출 ABAP 코드가 있으면 RFP·인터뷰를 최우선으로, 유사 사례는 힌트일 뿐.{_pb_wrap}""",
        agent=f_analyst,
        expected_output="요구사항 현황 분석 결과 (텍스트)",
    )
    mia_member = member_ref if member_ref else "없음"
    question_task = Task(
        description=f"""Hannah의 분석을 바탕으로 {round_num}라운드 첫 인터뷰 질문 1개만 생성하세요.

[내부 유사 사례·질문 후보]
{_format_library_block_for_mia(code_library_context)}

[회원이 본 요청에 제출한 ABAP 코드]
{mia_member}
{_ms_rule}

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}

질문은 한 가지 결정만 담는다. 고객(비전문가)이 이해할 수 있는 말로, 이전 라운드에서 끝난 주제는 반복하지 않는다.

또한 같은 JSON에 suggested_answers: 2~{MAX_SUGGESTED_ANSWERS}개(최대 {MAX_SUGGESTED_ANSWERS}개), 위 [답안 버튼] 규칙 준수.

출력(반드시 JSON, 한 블록):
{{"question": "...", "suggested_answers": ["...", "..."]}}""",
        agent=f_questioner,
        expected_output='{"question": "...", "suggested_answers": []}',
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
        q1, sugg = _parse_question_and_suggestions(str(result))
    except Exception:
        q1, sugg = "", []
    if not q1:
        q1 = _DEFAULT_QUESTIONS[0]
    if len(sugg) < 2:
        more = generate_suggested_answers_for_question(rfp_data, q1, round_num, 1)
        sugg = _normalize_suggested_answers(list(sugg) + list(more))
    src_out = agents_ai_source_ko("f_analyst", "f_questioner")
    if _interview_qa_enhance_enabled() and (q1 or "").strip():
        try:
            q1, sugg = run_interview_qa_enhancement(
                llm,
                rfp_data,
                conversation,
                round_num,
                "round-start",
                None,
                code_library_context,
                q1,
                sugg,
            )
            src_out = _interview_source_after_enhance()
        except Exception:
            pass
    return {
        "questions": [q1],
        "library_pool": [],
        "suggested_answers": sugg,
        "source": src_out,
    }


def generate_sequential_followup(
    rfp_data: dict,
    conversation: list[dict],
    round_num: int,
    in_round_qa: list[tuple[str, str]],
    code_library_context: str = "",
    library_pool: Optional[list] = None,
    member_safe_output: bool = False,
) -> dict:
    """
    이번 라운드: 조기 완료(round_complete) 또는 다음 질문 1개.
    library_pool 은 소모하지 않고 힌트로만 LLM에 넘깁니다(강제로 3문항 채우지 않음).
    """
    library_pool = [str(x).strip() for x in (library_pool or []) if str(x).strip()]

    analysis_summary, _ = _parse_code_library_context(code_library_context)
    member_ref = (rfp_data.get("reference_code_for_agents") or "").strip()
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)
    inr = _fmt_in_round(in_round_qa)
    n_done = len(in_round_qa)
    q_index = n_done + 1
    done_brief = "\n".join(
        f"  Q: {(q or '')[:220]}\n  A: {(a or '')[:500]}"
        for q, a in in_round_qa
    ) if in_round_qa else "(없음)"

    lib_for = ""
    if analysis_summary:
        lib_for = f"\n[유사 사례 요약]\n{analysis_summary[:2400]}\n"
    mref = ""
    if member_ref:
        mref = f"\n[회원이 본 요청에 제출한 ABAP 코드]\n{member_ref}\n"
    lib_block = _format_library_block_for_mia(code_library_context)
    lib_from_pool = ""
    pool_intro = (
        "유사 사례에서 뽑은 질문 후보(필수 아님, RFP에 맞지 않으면 무시. "
        "round_complete 로 이번 라운드를 먼저 끊어도 됨):\n"
        if member_safe_output
        else (
            "코드 라이브러리에서 뽑은 질문 후보(필수 아님, RFP에 맞지 않으면 무시. "
            "round_complete 로 이번 라운드를 먼저 끊어도 됨):\n"
        )
    )
    if library_pool:
        lib_from_pool = pool_intro + "\n".join(f"- {p[:400]}" for p in library_pool[:5])
    else:
        lib_from_pool = "(추가 질문 후보 없음)"
    _fol_ms = _MEMBER_FACING_NO_STORAGE_NAMES if member_safe_output else ""

    anti_dup = f"""[이번 라운드·이미 오간 Q&A(반복 금지 — **답 내용**까지 읽을 것)]
{done_brief}
- 위에서 사용자가 **이미 끊어 말한** 정책(Plant, Sales Order Type, 엑셀 오류 시 롤백 방식 등)을 **또 묻지 마라.**
- 같은 취지를 영어/한글 **표현만 바꿔** 다시 쓰는 것도 금지.
- 남는 것이 없으면 round_complete: true. RFP·구현에 **아직 열린 다른 한 가지**만 next_question(한 축)으로. RFP에 없으면 알림·승인·'특정 담당자'·일반 워크플로는 묻지 마라."""

    hard_cap = MAX_QUESTIONS_PER_ROUND
    decision_help = f"""[이번 라운드 현황]
- 지금 막 {n_done}개의 Q&A가 반영됨(회원이 방금 n_done번째 질문에 답함). 한 라운드 최대 {hard_cap}문항.
- RFP·답이 이미 충분하면 {{"round_complete": true, "next_question": null, "suggested_answers": []}} 만 반환(다음 질문 없음). 억지로 질문을 더 만들지 마라.
- 아직 꼭 물을 것이 있으면 round_complete: false, next_question(한 가지 결정) + suggested_answers.
- 지금 n_done이 {hard_cap}이면(이번 라운드에서 3문항을 모두 답한 경우) 반드시 round_complete: true. (다음 JSON에서는 next_question을 비운다)"""

    llm = _get_llm()
    f_analyst, f_questioner, _, _ = _make_agents(llm)
    _pb_f = playbook_prompt_wrap(playbook_addon)
    analyze_task = Task(
        description=f"""RFP·이전 라운드·이번 라운드까지의 Q&A를 읽고, 질문을 더 둘 필요가 있으면 한 문장 이유(내부용).

RFP: {rfp_ctx}
[이전 라운드]
{conv_ctx}
[이번 라운드 {round_num} – 지금까지]
{inr}
{lib_for}{mref}
{lib_from_pool}
{anti_dup}
{_fol_ms}
{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}{_pb_f}""",
        agent=f_analyst,
        expected_output="질문을 더할지, 이미 충분한지(한 문장)",
    )
    follow_task = Task(
        description=f"""Hannah의 요약과 아래 '이번 라운드' 답변을 반드시 반영해 JSON 한 덩어리만 출력하라.

[이번 라운드 Q&A (반드시 반영)]
{inr}

{decision_help}
{_fol_ms}

[내부 질문·요약(형식만 활용, 그대로 복붙 금지)]
{lib_block}

{lib_from_pool}

{anti_dup}

{MIA_INTERVIEW_SCOPE_AND_STYLE}
{SAP_INTERVIEW_CREDIBILITY}

- round_complete 가 true이면 next_question 은 null 또는 "" 이고, suggested_answers 는 빈 배열이어도 된다.
- round_complete 가 false이면 next_question: 15자 이상, **한 가지만**. 질문에 '또한/그리고'로 **두 주제**를 섞지 마라(선지에만 나열할 수 있는 **긴 시나리오**를 질문에 사전에 복붙하지 말라).
- suggested_answers: 2~{MAX_SUGGESTED_ANSWERS}개(위 [답안 버튼] 규칙). **각 항목은 next_question에 대한 응답만**, 한 항목에 **두 가지를 합쳐 쓰지 마라.**

출력 예시(형식만 참고, 내용은 RFP·답에 맞게):
{{"round_complete": false, "next_question": "...", "suggested_answers": ["...", "..."]}}
{{"round_complete": true, "next_question": null, "suggested_answers": []}}""",
        agent=f_questioner,
        expected_output='{"round_complete": true/false, "next_question": "...", "suggested_answers": []}',
        context=[analyze_task],
    )
    crew = Crew(
        agents=[f_analyst, f_questioner],
        tasks=[analyze_task, follow_task],
        process=Process.sequential,
        verbose=False,
    )
    try:
        out = str(crew.kickoff())
        parsed = _parse_followup_result(out)
    except Exception:
        parsed = {"round_complete": False, "next_question": "", "suggested_answers": []}

    rc = bool(parsed.get("round_complete"))
    nq = (parsed.get("next_question") or "").strip()
    sugg = list(parsed.get("suggested_answers") or [])

    if n_done >= hard_cap:
        return {
            "round_complete": True,
            "next_question": "",
            "library_pool": library_pool,
            "suggested_answers": [],
            "source": agents_ai_source_ko("f_analyst", "f_questioner"),
        }

    if rc:
        return {
            "round_complete": True,
            "next_question": "",
            "library_pool": library_pool,
            "suggested_answers": [],
            "source": agents_ai_source_ko("f_analyst", "f_questioner"),
        }

    if not nq or len(nq) < 15:
        if n_done >= 2:
            return {
                "round_complete": True,
                "next_question": "",
                "library_pool": library_pool,
                "suggested_answers": [],
                "source": agents_ai_source_ko("f_analyst", "f_questioner"),
            }
        i = min(n_done, len(_DEFAULT_QUESTIONS) - 1)
        nq = _DEFAULT_QUESTIONS[min(i + 1, len(_DEFAULT_QUESTIONS) - 1)]
    if len(sugg) < 2 and nq:
        more = generate_suggested_answers_for_question(
            rfp_data, nq, round_num, q_index
        )
        sugg = _normalize_suggested_answers(list(sugg) + list(more))
    src_fu = agents_ai_source_ko("f_analyst", "f_questioner")
    if nq and _interview_qa_enhance_enabled():
        try:
            nq, sugg = run_interview_qa_enhancement(
                llm,
                rfp_data,
                conversation,
                round_num,
                f"r{round_num}-q{q_index}",
                in_round_qa,
                code_library_context,
                nq,
                sugg,
            )
            src_fu = _interview_source_after_enhance()
        except Exception:
            pass
    return {
        "round_complete": False,
        "next_question": nq,
        "library_pool": library_pool,
        "suggested_answers": sugg,
        "source": src_fu,
    }


# ── Public API ────────────────────────────────────────

def generate_round_questions(
    rfp_data: dict,
    conversation: list[dict],
    round_num: int,
    code_library_context: str = "",
    member_safe_output: bool = False,
    playbook_addon: str = "",
) -> dict:
    """
    (호환) 한 라운드의 첫 질문 1개 + 라이브러리 풀. 레거시 코드가 3문항을 기대할 경우
    generate_sequential_start 후 연속 호출로 채울 수 있습니다.
    """
    return generate_sequential_start(
        rfp_data,
        conversation,
        round_num,
        code_library_context,
        member_safe_output=member_safe_output,
        playbook_addon=playbook_addon,
    )


def generate_proposal(
    rfp_data: dict,
    conversation: list[dict],
    code_library_context: str = "",
    member_safe_output: bool = False,
    playbook_addon: str = "",
) -> str:
    """
    전체 인터뷰 내용으로 Development Proposal을 생성합니다.
    f_analyst(최종 분석) → f_writer(작성) → f_reviewer(검토/승인) 순서로 진행합니다.
    """
    llm = _get_llm()
    f_analyst, _, f_writer, f_reviewer = _make_agents(llm)
    rfp_ctx = _fmt_rfp(rfp_data)
    conv_ctx = _fmt_conv(conversation)
    analysis_summary, _ = _parse_code_library_context(code_library_context)
    member_ref = (rfp_data.get("reference_code_for_agents") or "").strip()
    lib_for_hannah = ""
    if analysis_summary:
        lib_for_hannah = f"""

{_lib_block_heading(member_safe_output)}
{analysis_summary}
"""
    member_ref_block = _member_abap_block(member_ref)
    _prop_ms = _MEMBER_FACING_NO_STORAGE_NAMES if member_safe_output else ""
    _pb_prop = playbook_prompt_wrap(playbook_addon)

    # Task 1: Hannah – 최종 요구사항 명세
    final_analysis = Task(
        description=f"""아래 RFP와 전체 인터뷰 내용을 분석하여 최종 요구사항 명세를 작성하세요.

[RFP 정보]
{rfp_ctx}
{lib_for_hannah}{member_ref_block}
[전체 인터뷰 내용]
{conv_ctx}
{_prop_ms}

다음 항목을 포함한 구조화된 분석 결과를 작성하세요:
1. 프로그램 목적 및 배경
2. 핵심 기능 요구사항 목록
3. 입력 조건 및 출력 형태
4. SAP 모듈/컴포넌트 범위
5. 특이사항 및 제약조건
6. 복잡도 평가 (Low/Medium/High) 및 근거

※ 내부 유사 사례 요약·회원 제출 ABAP 코드가 있으면 화면·기술 패턴을 파악하는 데만 쓰고, 고객 RFP·인터뷰를 최우선으로 반영하세요.{_pb_prop}""",
        agent=f_analyst,
        expected_output="구조화된 최종 요구사항 명세 (텍스트)",
    )

    pid = (rfp_data.get("program_id") or "").strip()
    tcode = (rfp_data.get("transaction_code") or "").strip()
    customer_id_rule = ""
    if pid or tcode:
        customer_id_rule = f"""

**필수 (고객 입력 ID·T-Code):**
- RFP에 고객이 입력한 프로그램 ID가 있으면(`{pid or "없음"}`) 제안서·마크다운 전체에서 **프로그램명·실행 객체는 이 식별자만** 사용한다. 다른 Z/Y 이름을 임의로 제시하지 않는다.
- RFP에 고객이 입력한 트랜잭션 코드가 있으면(`{tcode or "없음"}`) **프로그램 실행은 이 T-Code만** 기술한다. 다른 트랜잭션 코드는 쓰지 않는다.
- 둘 다 없을 때만 Z/Y 프로그램명·T-Code를 합리적으로 제안할 수 있다."""

    # Task 2: Jun – Proposal 작성
    write_task = Task(
        description=f"""Hannah의 요구사항 명세를 바탕으로 Development Proposal을 작성하세요.
{customer_id_rule}
{_prop_ms}

아래 6개 섹션을 마크다운 형식으로 반드시 포함하세요:

# Development Proposal

## 1. 개발 개요
- 프로그램명: 고객이 RFP에 지정한 ID가 있으면 그 ID, 없을 때만 Z 또는 Y로 시작하는 제안명
- 개발 목적 및 배경
- 기대 효과 (비즈니스 관점으로 서술)
- 관련 SAP 표준 프로세스 및 T-Code(고객이 지정한 T-Code가 있으면 그것만)

## 2. 구현 기능
(고객이 이해할 수 있는 언어로 기능 목록 작성, 각 기능의 비즈니스 가치 포함)

## 3. 화면 구성
- **조회/입력/결과(ALV) 등** 구역을 소제목(###)으로 나누고, **각 구역의 필드 목록은 GFM 마크다운 표**로만 적는다. (일반회원이 읽기 쉽게. ASCII 아트/파이프만 나열된 난해한 형식 금지)
- **표 규칙(반드시):** 1) 헤더 한 줄, 2) 바로 다음 줄에 `|--------|` 형태 구분선, 3) 데이터 행, 4) **표 안에서는 행 사이에 빈 줄을 넣지 말 것.** 5) 열은 보통 | 필드명 | 필수 | 설명 | 처럼 3열 이하 권장.
- 조회 조건, 입력(ALV) 그리드, 결과 화면을 **각각** 표로 구분해 설명한다(실제 화면이 위→아래로 이해되게).

## 4. 처리 흐름
(1번부터 단계별로 프로그램 실행 흐름 기술, 최대 7단계)

## 5. 기술 사항
- 활용 SAP 컴포넌트 (T-Code, BAPI, 주요 테이블)
- 예상 개발 규모 (Small/Medium/Large)

## 6. 확인 필요 사항
(구현 전 고객과 반드시 확인해야 할 사항 목록)

작성 원칙: IT 비전문가도 이해 가능한 언어, SAP 용어는 괄호 안에 간단한 설명 추가. 리스트/표가 길어지면 **짧은 문단 + 표**로 정리해 스캔하기 쉽게 한다.
- **요구사항 ID 금지:** "FR001", "FR030" 등 **임의로 붙인** 기능/요구 코드·ID는 쓰지 마라. 필요하면 불릿 문장만.
- **논리·SAP 정합:** Order **수량**은 주문/입력 데이터다. "수량이 **자재 마스터**와 일치하는지 검증"처럼 **업무에 맞지 않는** 검증 문구는 넣지 마라. 필요한 것은 **자재 마스터 존재·단위·판가/가용** 등 **인터뷰·RFP에 근거**한 것만.
- **에이전트 표기:** AI 역할을 언급할 때는 인명/별명을 쓰지 말고, **「요구분석」 에이전트**, **「질의」 에이전트**, **「제안서」 에이전트**, **「제안검수」 에이전트**처럼 **대외명만「」** 로 감싼 뒤 공백 + **에이전트**로 쓴다.""",
        agent=f_writer,
        expected_output="완성된 Development Proposal (마크다운)",
        context=[final_analysis],
    )

    # Task 3: Sara – 검토 및 최종 승인
    _rev_extra = (
        "□ '코드 라이브러리', '서버 라이브러리', '내부 코드 DB' 등 저장소를 드러내는 문구가 있으면 중립적 표현으로 고친다\n"
        if member_safe_output
        else ""
    )
    review_task = Task(
        description=f"""Jun이 작성한 Development Proposal을 검토하세요.
{_prop_ms}

체크리스트:
{_rev_extra}
□ 6개 필수 섹션 (개발 개요, 구현 기능, 화면 구성, 처리 흐름, 기술 사항, 확인 필요 사항) 모두 포함
□ 프로그램명 (Z/Y로 시작) 포함
□ 기대 효과가 비즈니스 언어로 구체적으로 기술
□ 화면 구성이 구체적 (추상적 표현 없음)
□ IT 비전문가가 이해하기 어려운 표현 없음
□ 확인 필요 사항이 실질적이고 구체적
□ **"FR###"** 등 **임의 요구·기능 ID**가 있으면 **삭제**하거나 **일반 문장**으로 대체(고객이 쓰지 않은 ID는 쓰지 말 것)
□ **검증·통제** 서술이 **SAP/업무상 터무니없이** (예: 수량 vs 자재 마스터)면 **수정**하거나 삭제. 인터뷰·RFP **근거 없는** 기술은 제거

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


# ── 코드 라이브러리 / ABAP 분석 공통: 한국어 서술 품질 ─────────────────
SAP_KOREAN_CODE_ANALYSIS_STYLE = """
★ 한국어 서술 — SAP 실무자에게 익숙한 표현 (반드시)
- 영→한 직역어, 일반 비즈니스 잡어, 기계 번역체·과한 문어체를 피한다.
- SD/MM/PP 등 맥락에 맞게 **현장에서 통하는 용어**를 쓴다.
  (예: 맥락에 따라 납품·출고·미납, 오더 블록, 대금청구/빌링, 오픈 오더, 스케줄 라인 등.
  "미출 주문" 같이 쓰이지 않는 낯선 표현은 쓰지 말고, 소스·도메인에 맞는 표현으로 바꾼다.)
- program_purpose·screens의 title·summary_bullets·validations 등 **모든 한글 설명**에 동일하게 적용한다.
"""


# ── 코드 라이브러리 분석 (Hannah → Mia) ─────────────────

def analyze_code_for_library(
    source_code: str,
    title: str,
    modules: list[str],
    dev_types: list[str],
    *,
    include_interview_questions: bool = True,
    attachment_digest: str = "",
) -> dict:
    """
    ABAP 소스를 Hannah(기술 분석)로 분석하고, include_interview_questions=True일 때만
    Mia(신규 개발 인터뷰용 질문 추출)를 이어서 실행합니다.
    반환 dict는 DB `analysis_json`에 저장되며, 상세 화면은 `codelib_detail.html`에서 표시한다.

    Returns:
        program_purpose, screens[], validations, key_bapis, key_fms, applied_techniques, questions, error
        (+ 구 JSON 호환용 selection_screen, result_screen 키는 비어 있거나 LLM이 채울 수 있음)
    """
    llm = _get_llm()
    f_analyst, f_questioner, _, _ = _make_agents(llm)

    module_str = ", ".join(modules) if modules else "(미입력)"
    devtype_str = ", ".join(dev_types) if dev_types else "(미입력)"
    code_excerpt = trim_code_for_abap_analysis(source_code)
    att_txt = (attachment_digest or "").strip()
    att_block = ""
    if att_txt:
        att_block = f"\n\n[첨부·참고 자료 — 서버에서 추출한 텍스트 요약]\n{att_txt[:12000]}\n"

    _classify_advisory = """
★ 사용자 분류·태그 (반드시 준수)
- [프로그램 정보]의 SAP 모듈·개발 유형은 회원이 폼에서 선택·입력한 **태그**일 뿐이며 **오분류·누락이 흔하다**.
- 모듈 추정, 프로그램 성격, 구조·로직 해석은 **오직 ABAP 소스**에서 도출한다.
- 폼 태그와 소스 분석이 다르면 **소스 기준**으로 서술한다. 폼 태그는 참고용으로만 취급한다.
"""

    # ── Task 1: Hannah – 기술 분석 ────────────────────────
    analysis_task = Task(
        description=f"""아래 ABAP 소스 코드를 전문가 수준으로 분석하세요.

[프로그램 정보]
- 제목: {title}
- SAP 모듈: {module_str}
- 개발 유형: {devtype_str}
{_classify_advisory}
[ABAP 소스]
{code_excerpt}
{att_block}
★ 다중 프로그램
- 소스 상단에 `SAP_DEV_HUB:REF_SLOT` 등의 슬롯 구분 주석이 있거나 여러 목적이 섞여 보이면, **프로그램(슬롯)마다** 역할과 데이터 흐름을 구분해 `program_purpose`에 서술한다(한 문장 통합 요약만 하지 않는다).

다음 규칙을 지켜 반드시 아래 JSON 형식으로만 출력하세요.
- 출력은 유효한 JSON 객체 하나뿐입니다. JSON 앞뒤에 서론·결론·마크다운 제목을 쓰지 마세요.
- "program_purpose"에 위 [프로그램 정보]의 제목만 그대로 넣지 마세요. 소스 분석에 근거한 목적·역할을 2~3문장으로 서술하세요.
- "screens" 배열에는 이 프로그램에서 식별한 UI·실행 면을 최소 1개 포함하세요. (순수 배치면 그 성격을 한 항목으로 명시)
한국어로 작성하되, 기술 용어(BAPI명, FM명, 필드명, 화면 번호 등)는 영문 그대로 사용하세요.
{SAP_KOREAN_CODE_ANALYSIS_STYLE}

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

    question_task = None
    if include_interview_questions:
        # ── Task 2: Mia – 코드 라이브러리용 신규 개발 인터뷰 질문 ──────────────
        question_task = Task(
            description=f"""Hannah의 분석을 바탕으로,
신규 고객에게 공통으로 물어야 할 인터뷰 질문 3~5개를 추출하세요.
(참고: 폼의 "{module_str} + {devtype_str}" 태그는 **신뢰하지 말고**, Hannah가 **소스에서** 파악한 맥락을 따른다.)
{_classify_advisory}
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

    if include_interview_questions and question_task is not None:
        crew = Crew(
            agents=[f_analyst, f_questioner],
            tasks=[analysis_task, question_task],
            process=Process.sequential,
            verbose=True,
        )
    else:
        crew = Crew(
            agents=[f_analyst],
            tasks=[analysis_task],
            process=Process.sequential,
            verbose=True,
        )

    try:
        crew.kickoff()

        analysis_raw = _crew_task_output_text(analysis_task)
        question_raw = _crew_task_output_text(question_task) if question_task else ""

        analysis_data = _parse_json_block(analysis_raw, default={})
        question_data = (
            _parse_json_block(question_raw, default={"questions": []})
            if include_interview_questions
            else {"questions": []}
        )

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
                        f"{agent_label_ko('f_analyst')}의 분석 응답 텍스트를 찾지 못했습니다. "
                        "CrewAI 출력 필드가 비어 있거나 형식이 바뀌었을 수 있습니다."
                    ),
                }
            if not analysis_data:
                return {
                    **base,
                    "error": (
                        f"{agent_label_ko('f_analyst')}의 분석 응답을 JSON으로 읽지 못했습니다. "
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


def augment_abap_analysis_with_requirement(
    requirement_text: str,
    structural: dict,
    source_code: str,
    *,
    attachment_digest: str = "",
) -> dict:
    """
    코드 구조 분석(structural)에 더해, 회원이 입력한 요구사항과 연계한 추가 분석(JSON).
    """
    req = (requirement_text or "").strip()
    if not req:
        return {"error": "요구사항이 비었습니다."}
    llm = _get_llm()
    f_analyst, _, _, _ = _make_agents(llm)
    excerpt = trim_code_for_abap_analysis(source_code)
    att_txt = (attachment_digest or "").strip()
    att_block = ""
    if att_txt:
        att_block = f"\n\n[첨부·참고 자료 — 서버에서 추출한 텍스트 요약]\n{att_txt[:12000]}\n"
    summ = json.dumps(
        {
            "program_purpose": structural.get("program_purpose"),
            "key_bapis": structural.get("key_bapis"),
            "key_fms": structural.get("key_fms"),
            "screens": structural.get("screens"),
        },
        ensure_ascii=False,
    )[:12000]
    aug_task = Task(
        description=f"""회원이 작성한 **요구사항**과, 이미 수행된 **코드 구조 요약**·소스 일부를 바탕으로
오류 원인 추정, 개선/추가 시 영향, 확인할 점을 JSON으로 출력하라.

[요구사항 — 회원 입력]
{req[:15000]}

[구조 분석 요약 — 소스 기반]
{summ}

[ABAP 소스 일부]
{excerpt}
{att_block}
{SAP_KOREAN_CODE_ANALYSIS_STYLE}

출력 JSON 한 블록만 (한국어, 마크다운 제목 금지):
- "open_questions": **회원 요구사항**과 위 코드·요약에 **근거한** 확인만 (3개 이하 권장). 요구에 없는 신규 기능·범위를 가정한 질문·RFP식 인터뷰는 넣지 마라.
- 여러 프로그램 코드가 제출된 경우(소스에 슬롯 구분 주석이 있으면), 각 프로그램별로 요구사항과의 연계·부족 정보를 **구분해서** 서술하고, JSON 값(interpretation, mapping 등) 안에 프로그램 식별자(예: 프로그램명)를 포함해 가독성 있게 적는다.

{{
  "interpretation": "요구사항을 기술 관점에서 짧게 요약",
  "mapping": "요구와 코드상 어느 부분이 관련될 수 있는지",
  "suspected_areas": ["살펴볼 Include·폼·루틴·키워드"],
  "hypotheses": ["원인 또는 구현 가설"],
  "verification_suggestions": ["확인 방법(데이터, 브레이크포인트, T-Code 등)"],
  "open_questions": ["위 맥락에 맞는 확인 질문"]
}}""",
        agent=f_analyst,
        expected_output="JSON",
    )
    try:
        aug_crew = Crew(
            agents=[f_analyst],
            tasks=[aug_task],
            process=Process.sequential,
            verbose=False,
        )
        aug_crew.kickoff()
        raw = _crew_task_output_text(aug_task)
        data = _parse_json_block(raw, default={})
        if not data:
            return {"error": "요구사항 연계 분석 JSON을 읽지 못했습니다."}
        return {**data, "error": None}
    except Exception as e:
        return {"error": str(e)}


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
    """
    코드가 길 경우 줄 수를 줄입니다.

    「첫 줄부터 max_lines 줄」이 아니라, 앞 50줄 + 키워드(FORM, SELECT, LOOP 등)가
    있는 줄과 그 주변 + 마지막 30줄을 모은 뒤 max_lines 줄로 자릅니다.
    중간의 긴 FORM/SELECT 블록 전체가 빠질 수 있습니다.
    """
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


def trim_code_for_abap_analysis(source_code: str, max_lines: int | None = None) -> str:
    """
    `abap_source_only_from_reference_payload`가 넣은 슬롯 마커가 있으면
    프로그램별로 `_trim_code` 예산을 나눠, 첫 번째 프로그램만 남는 현상을 줄인다.
    """
    if max_lines is None:
        try:
            max_lines = int(os.environ.get("ABAP_ANALYSIS_TRIM_MAX_LINES", "4000"))
        except ValueError:
            max_lines = 4000
    src = source_code or ""
    if REF_SLOT_MARKER + "_BEGIN" not in src:
        return _trim_code(src, max_lines)
    begin = r"\*& === " + re.escape(REF_SLOT_MARKER) + r"_BEGIN[^\n]*\n"
    end = r"\n\*& === " + re.escape(REF_SLOT_MARKER) + r"_END[^\n]*"
    pat = re.compile(f"({begin})([\\s\\S]*?)({end})")
    ms = list(pat.finditer(src))
    if not ms:
        return _trim_code(src, max_lines)
    n = len(ms)
    per = max(80, max_lines // n)
    parts: list[str] = []
    pos = 0
    for m in ms:
        if m.start() > pos:
            orphan = src[pos : m.start()].strip()
            if orphan:
                parts.append(_trim_code(orphan, max(60, max_lines // (n + 1))))
        parts.append(m.group(1) + _trim_code(m.group(2), per) + m.group(3))
        pos = m.end()
    if pos < len(src):
        tail = src[pos:].strip()
        if tail:
            parts.append(_trim_code(tail, max(60, max_lines // (n + 1))))
    return "\n\n".join(parts).strip()


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
