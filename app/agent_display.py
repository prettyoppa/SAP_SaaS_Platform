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


# free_crew 내부 페르소나 — 고객 문서에 그대로 노출 금지
_FREE_CREW_PERSONA_NAMES: dict[str, str] = {
    "Hannah": "f_analyst",
    "Mia": "f_questioner",
    "Jun": "f_writer",
    "Sara": "f_reviewer",
}


def prepare_member_facing_proposal_markdown(text: str) -> str:
    """
    제안서 본문을 회원 화면용으로 정리합니다.
    wrap_unbracketed_agent_names + 페르소나 인명·1인칭 서두 제거.
    """
    out = wrap_unbracketed_agent_names(text or "")
    out = _strip_proposal_persona_opening(out)
    out = _replace_leaked_free_crew_personas(out)
    return out


def _strip_proposal_persona_opening(text: str) -> str:
    """# Development Proposal 앞의 Jun 서두 등 제거."""
    if not text:
        return text
    markers = ("# Development Proposal", "# Development", "## 1. 개발")
    for marker in markers:
        idx = text.find(marker)
        if 0 < idx < 1200:
            prefix = text[:idx].strip()
            if prefix and not prefix.lstrip().startswith("#"):
                lowered = prefix.lower()
                if any(
                    k in lowered
                    for k in (
                        "jun",
                        "hannah",
                        "mia",
                        "sara",
                        "컨설턴트",
                        "입니다",
                        "작성했습니다",
                        "제안서를",
                    )
                ):
                    return text[idx:].lstrip()
        elif idx == 0:
            break
    return text


def _replace_leaked_free_crew_personas(text: str) -> str:
    if not text:
        return text
    out = str(text)
    out = re.sub(
        r"SAP\s*컨설턴트\s*Jun(?:입니다|이)?[\.。]?\s*",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"컨설턴트\s*Jun(?:입니다|이)?[\.。]?\s*",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"Hannah님이\s*정리(?:해\s*주신|한)\s*",
        "요청·인터뷰에서 정리된 ",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"Hannah(?:님)?의\s*",
        f"{agent_label_ko('f_analyst')} ",
        out,
        flags=re.IGNORECASE,
    )
    for persona, role_id in _FREE_CREW_PERSONA_NAMES.items():
        label = agent_label_ko(role_id)
        out = re.sub(
            rf"\b{re.escape(persona)}(?:님)?\b",
            label,
            out,
            flags=re.IGNORECASE,
        )
    return out


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
