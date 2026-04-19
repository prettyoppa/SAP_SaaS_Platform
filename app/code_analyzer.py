"""
ABAP Code Analyzer – SAP Dev Hub

실제 ABAP 소스 코드를 Gemini로 분석하여:
1. 프로그램의 목적·구조·로직을 파악
2. 이 코드를 짜기 위해 RFP 단계에서 반드시 물어야 했던 질문을 역방향으로 추출

추출된 질문은 인터뷰 엔진(interview_engine.py)에서
유사한 신규 RFP의 1라운드 질문으로 재활용됩니다.
"""

import json
import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from .gemini_model import get_gemini_model_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _get_model() -> genai.GenerativeModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_gemini_model_id())


def analyze_abap_code(source_code: str, title: str, modules: list[str], dev_types: list[str]) -> dict:
    """
    ABAP 소스 코드를 분석하여 구조 정보와 역방향 인터뷰 질문을 반환합니다.

    Returns:
        {
            "program_purpose": str,
            "key_bapis": [str, ...],
            "key_fms": [str, ...],
            "input_fields": [str, ...],
            "output_type": str,
            "key_logics": [str, ...],
            "questions": [str, ...],   ← 역추출 질문 (최대 5개)
            "error": str | None
        }
    """
    model = _get_model()

    module_str = ", ".join(modules)
    dev_type_str = ", ".join(dev_types)

    # 코드가 너무 길면 앞뒤 중요 부분만 추출 (토큰 절약)
    code_excerpt = _extract_key_sections(source_code)

    prompt = f"""당신은 SAP 프로젝트 경험이 풍부한 선임 컨설턴트입니다.
아래 ABAP 소스 코드를 분석하여 JSON으로 응답해 주세요.

[코드 정보]
- 프로그램명/설명: {title}
- SAP 모듈: {module_str}
- 개발 유형: {dev_type_str}

[ABAP 소스 코드]
{code_excerpt}

[분석 지시사항]

Step 1: 코드를 읽고 프로그램의 목적, 사용 BAPI/FM, 입출력 구조, 핵심 로직을 파악하세요.

Step 2: 신규 고객이 "{module_str} + {dev_type_str}" 유형의 유사한 개발을 요청했을 때
컨설턴트가 고객에게 물어야 하는 인터뷰 질문 3~5개를 도출하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 반드시 지켜야 하는 질문 작성 형식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

아래 4개의 예시가 원하는 질문의 정확한 형식과 수준입니다.
이 예시들을 참고하여 동일한 스타일로 작성하세요.

[예시 1] 데이터 마스킹 처리(고객 정보, 가격 정보 등)가 필요한 필드가 있나요?
         있다면, 어떤 규칙으로 마스킹해야 할까요?

[예시 2] 보고서에서 '완료'로 간주되는 상태는 무엇인가요?
         (예: 전체 납품 완료, 전체 Invoice 발행 완료)
         이 상태를 기준으로 데이터를 필터링하거나 특정 색상으로 강조 표시해야 할까요?

[예시 3] 판매 오더 추적 시, 전체 오더 흐름 외에 특정 이슈(예: 납기 지연, 재고 부족, 반품)를
         강조하여 보여줄 필요가 있나요? 있다면 어떤 기준으로 판단해야 하나요?

[예시 4] ALV 그리드 외에 추가적인 데이터 시각화(예: 차트, 그래프)가 필요한가요?
         필요하다면 어떤 종류의 시각화가 유용할까요? (예: 기간별 판매 추이, 지역별 판매 현황)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 좋은 질문의 핵심 특성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. "필요한가요? + 있다면 어떤 기준으로?" 구조로 작성 (고객이 Yes/No 후 세부사항 답변 가능)
2. 괄호 안에 구체적인 예시를 반드시 포함 (예: 고객이 어떤 답을 해야 하는지 힌트 제공)
3. 고객사마다 답이 달라지는 비즈니스 의사결정 사항을 질문 (개발자가 혼자 결정하면 안 되는 것)
4. SAP 용어를 사용하되 고객 담당자(비개발자)도 이해할 수 있는 표현
5. 이 코드를 기반으로 도출하되, 어느 회사의 유사 요청에도 공통 적용 가능한 질문

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 절대 피해야 할 질문 유형
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- "어떤 SAP 모듈을 사용하나요?" (이미 분류에서 알 수 있음)
- "어떤 테이블을 조회할까요?" (개발자가 결정하는 사항)
- "시스템 성능 요건은?" (RFP 수준에서 묻기엔 너무 기술적)
- "프로그램 구조를 어떻게 할까요?" (개발자 설계 영역)

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "program_purpose": "프로그램 목적 한 문장 요약",
  "key_bapis": ["BAPI명1", "BAPI명2"],
  "key_fms": ["FM명1"],
  "input_fields": ["필드1(SAP명)", "필드2(SAP명)"],
  "output_type": "ALV Grid / 파일 Export / 메시지 출력 등",
  "key_logics": ["핵심 로직 1", "핵심 로직 2"],
  "questions": [
    "질문1 (위 예시 형식과 동일한 스타일로)",
    "질문2",
    "질문3",
    "질문4",
    "질문5"
  ]
}}"""

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # 코드펜스 제거
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1).strip()

        result = json.loads(raw)
        result["error"] = None
        return result

    except json.JSONDecodeError as e:
        return {
            "program_purpose": title,
            "key_bapis": [],
            "key_fms": [],
            "input_fields": [],
            "output_type": "불명확",
            "key_logics": [],
            "questions": [],
            "error": f"JSON 파싱 실패: {e}",
        }
    except Exception as e:
        return {
            "program_purpose": title,
            "key_bapis": [],
            "key_fms": [],
            "input_fields": [],
            "output_type": "불명확",
            "key_logics": [],
            "questions": [],
            "error": str(e),
        }


def _extract_key_sections(source_code: str, max_lines: int = 300) -> str:
    """
    코드가 길 경우 핵심 섹션(선언부 + 주요 로직)만 추출합니다.
    Selection Screen, BAPI 호출부, 주요 로직이 포함되도록 합니다.
    """
    lines = source_code.splitlines()
    if len(lines) <= max_lines:
        return source_code

    # 항상 포함: 앞 50줄 (TYPES, DATA, SELECTION-SCREEN 선언부)
    head = lines[:50]

    # 키워드가 있는 중요 섹션 탐색
    keywords = [
        "SELECTION-SCREEN", "PARAMETERS", "SELECT-OPTIONS",
        "CALL FUNCTION", "BAPI_", "BAPI ",
        "FORM ", "ENDFORM",
        "LOOP AT", "READ TABLE",
        "MESSAGE", "RETURN",
    ]
    important_lines = []
    for i, line in enumerate(lines[50:], start=50):
        if any(kw in line.upper() for kw in keywords):
            start = max(50, i - 2)
            end = min(len(lines), i + 5)
            important_lines.extend(lines[start:end])

    # 마지막 30줄
    tail = lines[-30:]

    combined = head + ["... (중략) ..."] + list(dict.fromkeys(important_lines)) + ["... (중략) ..."] + tail
    return "\n".join(combined[:max_lines])


def find_similar_codes(db_session, sap_modules: list[str], dev_types: list[str]) -> list:
    """
    DB에서 모듈·개발유형이 겹치는 분석 완료된 ABAP 코드를 검색합니다.
    매칭 점수(겹치는 항목 수)가 높은 순으로 반환합니다.
    """
    from .models import ABAPCode

    all_codes = db_session.query(ABAPCode).filter(
        ABAPCode.is_analyzed == True,
        ABAPCode.questions_json != None,
    ).all()

    scored = []
    for code in all_codes:
        code_modules = set(code.sap_modules.split(",")) if code.sap_modules else set()
        code_devtypes = set(code.dev_types.split(",")) if code.dev_types else set()
        req_modules = set(sap_modules)
        req_devtypes = set(dev_types)

        module_score = len(code_modules & req_modules)
        devtype_score = len(code_devtypes & req_devtypes) * 2  # 개발유형 일치를 더 중요하게

        total = module_score + devtype_score
        if total > 0:
            scored.append((total, code))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [code for _, code in scored[:3]]  # 최대 3개 반환


def extract_questions_from_codes(similar_codes: list) -> list[str]:
    """
    유사 코드들에서 역추출된 질문을 합쳐서 중복 없이 반환합니다.
    """
    seen = set()
    merged = []
    for code in similar_codes:
        if not code.questions_json:
            continue
        try:
            questions = json.loads(code.questions_json)
            for q in questions:
                q_key = q.strip().lower()[:50]
                if q_key not in seen:
                    seen.add(q_key)
                    merged.append(q)
        except Exception:
            pass
    return merged[:5]  # 최대 5개
