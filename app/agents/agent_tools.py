"""
Agent Tools – SAP Dev Hub
에이전트가 사용하는 공용 헬퍼 함수들.
DB 세션은 라우터에서 미리 조회하여 context 문자열로 전달합니다.
(CrewAI Tool 객체가 아닌 순수 함수 방식 – DB 세션 생명주기 문제 회피)
"""

import json


def get_code_library_context(
    db_session,
    sap_modules: list[str],
    dev_types: list[str],
    *,
    member_safe_output: bool = False,
) -> str:
    """
    유사 ABAP 사례를 찾아 JSON 문자열로 반환합니다.
    member_safe_output=True: 일반 회원 RFP용 — 산출물에 저장소 명칭이 새지 않도록 요약·source 문구 완화.
    """
    try:
        from ..code_analyzer import (
            find_similar_codes,
            extract_questions_from_codes,
            format_similar_codes_analysis_summary,
        )
        similar = find_similar_codes(db_session, sap_modules, dev_types)
        if not similar:
            return ""
        analysis_summary = format_similar_codes_analysis_summary(
            similar, for_member_output=member_safe_output
        )
        questions = extract_questions_from_codes(similar)
        matched = " / ".join(c.title for c in similar[:2])
        src = (
            f"내부 유사 사례 기반 ({matched})"
            if member_safe_output
            else f"코드 라이브러리 기반 ({matched})"
        )
        out: dict = {
            "analysis_summary": analysis_summary,
            "source": src,
        }
        if questions:
            out["questions"] = questions
        return json.dumps(out, ensure_ascii=False)
    except Exception:
        return ""
