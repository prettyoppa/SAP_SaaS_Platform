"""
사이트(회원)에 노출하는 에이전트 표기 – 대외명은 「…」 안에, 뒤에 공백 + '에이전트'.
내부 페르소나(Mia, Jun 등)는 UI/API 사용자 문자열에 쓰지 않습니다.
"""

from __future__ import annotations

import re

# 기능 ID → 화면용 대외명(초단형, 한)
AGENT_SHORT_KO: dict[str, str] = {
    "f_analyst": "요구분석",
    "f_questioner": "질의",
    "f_writer": "제안서",
    "f_reviewer": "제안검수",
    "p_architect": "FS설계",
    "p_coder": "ABAP",
    "p_inspector": "코드검수",
    "p_tester": "테스트",
}

# 영문(홈/How it works 등) – 대외명
AGENT_SHORT_EN: dict[str, str] = {
    "f_analyst": "Requirements",
    "f_questioner": "Q&A",
    "f_writer": "Proposal",
    "f_reviewer": "Review",
    "p_architect": "FS Design",
    "p_coder": "ABAP",
    "p_inspector": "Code Review",
    "p_tester": "Test",
}


def agent_label_ko(role_id: str) -> str:
    """예: f_analyst → '「요구분석」 에이전트' (대외명만 「」)"""
    short = AGENT_SHORT_KO.get(role_id, role_id)
    return f"「{short}」 에이전트"


def agent_label_en(role_id: str) -> str:
    """예: f_analyst → '「Requirements」 Agent'"""
    short = AGENT_SHORT_EN.get(role_id, role_id)
    return f"「{short}」 Agent"


def agents_ai_source_ko(*role_ids: str) -> str:
    """JSON source 등: AI 에이전트 생성 (「요구분석」 에이전트, 「질의」 에이전트)"""
    return "AI 에이전트 생성 (" + ", ".join(agent_label_ko(r) for r in role_ids) + ")"


def wrap_unbracketed_agent_names(text: str) -> str:
    """
    본문/HTML/마크다운에 남은 옛 표기를 「대외명」 에이전트 형태로 통일합니다.
    - 구형: 「요구분석 에이전트」(전체가 한 괄호 안) → 「요구분석」 에이전트
    - 영문 구형: 「Requirements Agent」 → 「Requirements」 Agent
    - 괄호 없음: 요구분석 에이전트 → 「요구분석」 에이전트
    """
    if not text or not str(text).strip():
        return text
    out = str(text)

    # 1) 구형(이전 구현): 「{short} 에이전트」 전체가 한 덩어리
    for short in sorted(set(AGENT_SHORT_KO.values()), key=len, reverse=True):
        old = f"「{short} 에이전트」"
        new = f"「{short}」 에이전트"
        out = out.replace(old, new)
    for short in sorted(set(AGENT_SHORT_EN.values()), key=len, reverse=True):
        old = f"「{short} Agent」"
        new = f"「{short}」 Agent"
        out = out.replace(old, new)

    # 2) 괄호 없이 '대외명 + 에이전트' (한국어만; 영문 bare는 Unit Test Agent 등 오탐 가능)
    for short in sorted(set(AGENT_SHORT_KO.values()), key=len, reverse=True):
        bare = f"{short} 에이전트"
        canonical = f"「{short}」 에이전트"
        esc = re.escape(bare)
        out = re.sub(r"(?<!「)" + esc + r"(?!」)", canonical, out)

    return out
