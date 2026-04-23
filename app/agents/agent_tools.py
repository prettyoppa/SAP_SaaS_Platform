"""
Agent Tools – SAP Dev Hub
에이전트가 사용하는 공용 헬퍼 함수들.
DB 세션은 라우터에서 미리 조회하여 context 문자열로 전달합니다.
(CrewAI Tool 객체가 아닌 순수 함수 방식 – DB 세션 생명주기 문제 회피)
"""

import json


def get_code_library_context(db_session, sap_modules: list[str], dev_types: list[str]) -> str:
    """
    코드 라이브러리에서 유사 코드를 찾아 JSON 문자열로 반환합니다.
    - analysis_summary: Hannah·Proposal용 프로그램 요약 (항상 유사 코드가 있으면 포함)
    - questions: 역추출 인터뷰 질문 (있을 때만)
    이 함수는 라우터에서 호출하여 에이전트 Task description에 주입합니다.

    Returns:
        JSON 문자열 또는 빈 문자열
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
        analysis_summary = format_similar_codes_analysis_summary(similar)
        questions = extract_questions_from_codes(similar)
        matched = " / ".join(c.title for c in similar[:2])
        out: dict = {
            "analysis_summary": analysis_summary,
            "source": f"코드 라이브러리 기반 ({matched})",
        }
        if questions:
            out["questions"] = questions
        return json.dumps(out, ensure_ascii=False)
    except Exception:
        return ""
