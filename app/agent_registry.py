"""
플랫폼 AI 에이전트 8종 — 관리자·문서용 단일 레지스트리.

회원 UI에는 agent_display.agent_label_ko() 대외명만 노출하고,
내부 페르소나(Hannah, Mia 등)는 프롬프트·운영 화면에서만 참고합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .agent_display import AGENT_SHORT_EN, AGENT_SHORT_KO

Tier = Literal["free", "paid"]


@dataclass(frozen=True)
class AgentSpec:
    role_id: str
    legacy_role: str
    persona: str
    tier: Tier
    category_ko: str
    category_en: str
    crew_module: str
    workflow_ko: str
    used_in_ko: tuple[str, ...]
    playbook_stages: tuple[str, ...]


def all_agent_specs() -> tuple[AgentSpec, ...]:
    """등록 순서 = 일반적인 파이프라인 순서."""
    return (
        AgentSpec(
            role_id="f_analyst",
            legacy_role="analyst_agent",
            persona="Hannah",
            tier="free",
            category_ko=AGENT_SHORT_KO["f_analyst"],
            category_en=AGENT_SHORT_EN["f_analyst"],
            crew_module="app/agents/free_crew.py",
            workflow_ko=(
                "RFP·인터뷰 답변을 구조화된 요구 명세로 정리. "
                "인터뷰 라운드마다 질문 적합성 1차 판정(INTERVIEW_QA_ENHANCE). "
                "ABAP 분석·개선: 참조 코드 구조 분석 + 요구사항 연계 분석. "
                "코드 갤러리 업로드 시 기술 분석."
            ),
            used_in_ko=(
                "신규 개발 — 인터뷰·제안서 전 단계",
                "연동 개발 — 인터뷰·제안서 전 단계",
                "ABAP 분석·개선 — 분석 결과(코드·연계)",
                "ABAP 코드 갤러리 — 소스 분석",
            ),
            playbook_stages=("interview", "proposal", "analysis"),
        ),
        AgentSpec(
            role_id="f_questioner",
            legacy_role="question_agent",
            persona="Mia",
            tier="free",
            category_ko=AGENT_SHORT_KO["f_questioner"],
            category_en=AGENT_SHORT_EN["f_questioner"],
            crew_module="app/agents/free_crew.py",
            workflow_ko=(
                "코드 갤러리·분석 맥락과 f_analyst 결과를 바탕으로 "
                "라운드당 인터뷰 질문 1개 + 선택 답안 생성. "
                "불합격 시 1회 재작성 후 f_reviewer 최종 확정."
            ),
            used_in_ko=(
                "신규 개발 — 요구 인터뷰(최대 3라운드)",
                "연동 개발 — 요구 인터뷰",
                "ABAP 코드 갤러리 — 신규 개발용 질문 추출(옵션)",
            ),
            playbook_stages=("interview",),
        ),
        AgentSpec(
            role_id="f_writer",
            legacy_role="proposal_agent",
            persona="Jun",
            tier="free",
            category_ko=AGENT_SHORT_KO["f_writer"],
            category_en=AGENT_SHORT_EN["f_writer"],
            crew_module="app/agents/free_crew.py",
            workflow_ko=(
                "f_analyst 요구 명세를 바탕으로 Development Proposal 초안 작성. "
                "일반 사용자도 이해할 수 있는 고객용 제안서 톤."
            ),
            used_in_ko=(
                "신규 개발 — 제안서",
                "연동 개발 — 제안서",
                "ABAP 분석·개선 — 제안서(인터뷰 생략, 분석·연계 시드 1라운드)",
            ),
            playbook_stages=("proposal",),
        ),
        AgentSpec(
            role_id="f_reviewer",
            legacy_role="proposal_reviewer",
            persona="Sara",
            tier="free",
            category_ko=AGENT_SHORT_KO["f_reviewer"],
            category_en=AGENT_SHORT_EN["f_reviewer"],
            crew_module="app/agents/free_crew.py",
            workflow_ko=(
                "제안서 필수 항목·모호 표현 검수 후 보완·[APPROVED] 최종본. "
                "인터뷰 질문·선지 품질 최종 확정(INTERVIEW_QA_ENHANCE)."
            ),
            used_in_ko=(
                "신규/연동 — 제안서 검수",
                "신규/연동 — 인터뷰 Q&A 품질 최종",
                "ABAP 분석·개선 — 제안서 검수",
            ),
            playbook_stages=("interview", "proposal"),
        ),
        AgentSpec(
            role_id="p_architect",
            legacy_role="consultant_agent",
            persona="David",
            tier="paid",
            category_ko=AGENT_SHORT_KO["p_architect"],
            category_en=AGENT_SHORT_EN["p_architect"],
            crew_module="app/agents/paid_crew.py",
            workflow_ko=(
                "요구·인터뷰·제안서를 교차 검증해 구현 착수 가능한 상세 FS(기능명세) 마크다운 작성. "
                "GOOGLE_API_KEY 없으면 가짜 문서 없이 실패."
            ),
            used_in_ko=(
                "신규 개발 — FS(유료·관리자 생성)",
                "ABAP 분석·개선 — FS",
                "연동 개발 — FS",
            ),
            playbook_stages=("fs_abap", "integration_fs"),
        ),
        AgentSpec(
            role_id="p_coder",
            legacy_role="abap_agent",
            persona="Kevin",
            tier="paid",
            category_ko=AGENT_SHORT_KO["p_coder"],
            category_en=AGENT_SHORT_EN["p_coder"],
            crew_module="app/agents/paid_crew.py · app/agents/integration_deliverable_crew.py",
            workflow_ko=(
                "FS를 입력으로 납품 ABAP JSON 슬롯(프로그램별 소스) + 구현·운영 가이드 마크다운 생성. "
                "실패 시 레거시 단일 마크다운 폴백."
            ),
            used_in_ko=(
                "신규 개발 — 납품 ABAP",
                "ABAP 분석·개선 — 납품 ABAP",
                "연동 개발 — 구현 가이드·납품 JSON",
            ),
            playbook_stages=("delivered_abap", "integration_deliverable"),
        ),
        AgentSpec(
            role_id="p_inspector",
            legacy_role="code_reviewer",
            persona="Young",
            tier="paid",
            category_ko=AGENT_SHORT_KO["p_inspector"],
            category_en=AGENT_SHORT_EN["p_inspector"],
            crew_module="app/agents/paid_crew.py",
            workflow_ko="p_coder 산출 JSON·코드를 검수하고 수정 지시 → p_coder가 반영(순차 Crew).",
            used_in_ko=(
                "신규 개발 — 납품 ABAP 검수 루프",
                "ABAP 분석·개선 — 납품 ABAP 검수",
            ),
            playbook_stages=("delivered_abap",),
        ),
        AgentSpec(
            role_id="p_tester",
            legacy_role="qa_agent",
            persona="Brian",
            tier="paid",
            category_ko=AGENT_SHORT_KO["p_tester"],
            category_en=AGENT_SHORT_EN["p_tester"],
            crew_module="app/agents/paid_crew.py · app/agents/integration_deliverable_crew.py",
            workflow_ko="납품 ABAP·FS 맥락으로 단위 테스트 시나리오(약 10건) 마크다운 작성.",
            used_in_ko=(
                "신규 개발 — 테스트 시나리오",
                "ABAP 분석·개선 — 테스트 시나리오",
                "연동 개발 — 테스트 시나리오",
            ),
            playbook_stages=("delivered_abap", "integration_deliverable"),
        ),
    )


def agent_registry_summary() -> dict[str, int]:
    specs = all_agent_specs()
    return {
        "total": len(specs),
        "free": sum(1 for s in specs if s.tier == "free"),
        "paid": sum(1 for s in specs if s.tier == "paid"),
    }


def pipeline_steps_ko() -> tuple[str, ...]:
    return (
        "요청 제출 → (신규/연동) f_analyst·f_questioner 인터뷰 → f_writer·f_reviewer 제안서",
        "ABAP 분석·개선: f_analyst 분석·연계 → f_writer·f_reviewer 제안서(인터뷰 생략)",
        "유료: p_architect FS → p_coder → p_inspector → p_tester 납품 패키지",
        "운영 규칙: Admin 에이전트 플레이북이 단계별 프롬프트에 주입",
        "실행 엔진: CrewAI + Google Gemini (GOOGLE_API_KEY)",
    )


def agents_overview_ui() -> dict[str, object]:
    """Admin /admin/agents 화면 정적 문구 (템플릿 인코딩 이슈 방지용)."""
    return {
        "page_title": "AI 에이전트 구성 – Admin",
        "heading": "AI 에이전트 구성",
        "intro": (
            "Catchy Lab SAP Dev Hub에서 실제로 호출되는 8개 CrewAI 에이전트입니다. "
            "회원 화면에는 대외명(예: 「요구분석」 에이전트)만 표시되고, "
            "페르소나 이름은 프롬프트·운영 참고용입니다."
        ),
        "card_total": "전체",
        "card_free_desc": "요구분석 · 질의 · 제안서 · 제안검수",
        "card_paid_desc": "FS설계 · ABAP · 코드검수 · 테스트",
        "pipeline_heading": "전체 파이프라인",
        "playbook_link": "에이전트 플레이북",
        "playbook_hint": "에서 단계별 운영 규칙을 추가하면 위 에이전트 프롬프트에 자동 주입됩니다.",
        "detail_heading": "에이전트 상세",
        "detail_badge": "역할 ID = 코드·로그 기준",
        "col_role_id": "역할 ID",
        "col_legacy": "구형 이름",
        "col_persona": "페르소나",
        "col_tier": "티어",
        "col_label": "대외명",
        "col_workflow": "역할·워크플로",
        "col_menus": "적용 메뉴",
        "col_playbook": "플레이북 단계",
        "notes_heading": "참고",
        "notes": (
            "ABAP 분석·개선은 인터뷰 단계 없이 f_analyst(분석·연계) → f_writer·f_reviewer(제안서)로 이어집니다.",
            "인터뷰 질문 품질 강화: 환경변수 INTERVIEW_QA_ENHANCE(기본 on) — f_analyst 합불 → f_questioner 재작성 → f_reviewer 최종.",
            "납품 ABAP: p_coder JSON 슬롯 → p_inspector 검수 → p_tester 시나리오(순차 Gemini 호출).",
        ),
    }
