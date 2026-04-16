"""
Interview Engine – SAP Dev Hub
RFP 제출 내용을 분석하여 단계적 질문을 생성하고,
충분한 정보가 수집되면 Development Proposal을 작성합니다.

LLM: Google Gemini 2.0 Flash (SAP_AI_Agent와 동일 모델)
최대 라운드: 3  / 라운드당 질문: 3개
"""

import json
import os
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_ROUNDS = 3

_SAP_MODULE_LABELS = {
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

_DEV_TYPE_LABELS = {
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


def _get_model() -> genai.GenerativeModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY가 설정되지 않았습니다. "
            "SAP_SaaS_Platform/.env 파일에 GOOGLE_API_KEY를 추가하세요."
        )
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def _format_rfp_context(rfp_data: dict) -> str:
    modules = [_SAP_MODULE_LABELS.get(m, m) for m in rfp_data.get("sap_modules", [])]
    dev_types = [_DEV_TYPE_LABELS.get(d, d) for d in rfp_data.get("dev_types", [])]
    return (
        f"- 요청 제목: {rfp_data.get('title', '(없음)')}\n"
        f"- SAP 모듈: {', '.join(modules) if modules else '(미선택)'}\n"
        f"- 개발 유형: {', '.join(dev_types) if dev_types else '(미선택)'}\n"
        f"- 요구사항 설명:\n{rfp_data.get('description', '(없음)')}"
    )


def _format_conversation(messages: list[dict]) -> str:
    if not messages:
        return "(이전 인터뷰 없음)"
    parts = []
    for msg in messages:
        parts.append(f"[{msg['round_number']}라운드 질문]")
        for i, q in enumerate(msg["questions"], 1):
            parts.append(f"  Q{i}. {q}")
        if msg.get("answers_text"):
            parts.append(f"[{msg['round_number']}라운드 답변]\n  {msg['answers_text']}")
    return "\n".join(parts)


def generate_questions(rfp_data: dict, conversation: list[dict], db_session=None) -> dict:
    """
    현재까지 수집된 정보를 분석하여 다음 질문 3개를 생성합니다.

    Returns:
        {
            "questions": ["질문1", "질문2", "질문3"],
            "is_complete": bool,
            "completion_reason": str
        }
    """
    from . import code_analyzer

    current_round = len(conversation) + 1

    if current_round > MAX_ROUNDS:
        return {
            "questions": [],
            "is_complete": True,
            "completion_reason": f"최대 {MAX_ROUNDS}라운드 인터뷰가 완료되었습니다.",
        }

    # ── 1라운드: 코드 라이브러리에서 유사 코드의 역추출 질문 우선 사용 ──────
    if current_round == 1 and db_session is not None:
        modules = rfp_data.get("sap_modules", [])
        dev_types = rfp_data.get("dev_types", [])
        similar_codes = code_analyzer.find_similar_codes(db_session, modules, dev_types)
        if similar_codes:
            questions = code_analyzer.extract_questions_from_codes(similar_codes)
            if questions:
                matched_titles = " / ".join(c.title for c in similar_codes[:2])
                return {
                    "questions": questions,
                    "is_complete": False,
                    "completion_reason": "",
                    "source": f"코드 라이브러리 기반 ({matched_titles})",
                }

    model = _get_model()
    rfp_context = _format_rfp_context(rfp_data)
    conv_context = _format_conversation(conversation)

    prompt = f"""당신은 SAP 전문 컨설턴트입니다.
고객의 개발 요청과 지금까지 진행한 인터뷰 내용을 분석하여,
완전한 Functional Specification(FS)을 작성하기 위해 아직 부족한 핵심 정보를 파악하고 질문을 생성하세요.

[고객 개발 요청 정보]
{rfp_context}

[지금까지의 인터뷰 내용]
{conv_context}

[현재 라운드: {current_round} / 최대 {MAX_ROUNDS}]

지시사항:
1. 위 정보를 바탕으로 FS 작성에 반드시 필요하지만 아직 불명확한 정보를 파악하세요.
2. 가장 중요한 질문 3개를 생성하세요.
3. 이미 답변된 내용은 다시 묻지 마세요.
4. 질문은 SAP 실무 관점에서 구체적이고 명확해야 합니다.
   예시: "오더 타입(Order Type)은 표준 OR인가요, 아니면 별도 CBO 타입인가요?"
5. 충분한 정보가 수집되어 FS 작성이 가능하다면 is_complete를 true로 설정하세요.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "questions": ["질문1", "질문2", "질문3"],
  "is_complete": false,
  "completion_reason": ""
}}"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # JSON 파싱 (코드펜스 제거)
    if "```" in raw:
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            raw = match.group(1).strip()

    try:
        result = json.loads(raw)
        # 필드 검증
        if "questions" not in result:
            result["questions"] = ["추가 정보를 입력해 주세요."]
        if "is_complete" not in result:
            result["is_complete"] = False
        if "completion_reason" not in result:
            result["completion_reason"] = ""
        return result
    except json.JSONDecodeError:
        # JSON 파싱 실패 시 기본 질문 반환
        return {
            "questions": [
                "요구사항을 좀 더 구체적으로 설명해 주실 수 있나요?",
                "예상 사용자 수와 데이터 처리 규모는 어느 정도인가요?",
                "기존에 참고할 수 있는 유사 프로그램이나 화면이 있나요?",
            ],
            "is_complete": False,
            "completion_reason": "",
        }


def generate_proposal(rfp_data: dict, conversation: list[dict]) -> str:
    """
    수집된 모든 정보를 바탕으로 5개 항목의 Development Proposal을 생성합니다.
    """
    model = _get_model()

    rfp_context = _format_rfp_context(rfp_data)
    conv_context = _format_conversation(conversation)

    prompt = f"""당신은 SAP 수석 컨설턴트입니다.
아래 고객 요구사항과 인터뷰 내용을 바탕으로 전문적인 Development Proposal을 작성하세요.
이 Proposal은 고객이 "내 요구사항이 정확히 접수되었구나"를 확인할 수 있는 수준이어야 합니다.

[고객 개발 요청 정보]
{rfp_context}

[인터뷰 전체 내용]
{conv_context}

아래 5개 항목으로 구성된 Development Proposal을 작성하세요.
각 항목은 SAP 전문 용어와 실무 경험을 반영하여 구체적으로 작성하세요.

---

# Development Proposal

## 1. 개발개요
- 프로그램명 (제안): [ZXxx 형태의 프로그램명 제안]
- 개발 목적 및 배경
- 기대 효과
- 관련 SAP 표준 프로세스 및 T-Code

## 2. 화면개요
- Selection Screen 입력 항목 (필드명, 유형, 필수여부)
- 출력 화면 구성 (ALV 컬럼 목록 또는 기타 출력 형태)

## 3. 화면흐름
프로그램 실행 단계별 흐름을 번호 목록으로 작성:
1. (첫 번째 단계)
2. (두 번째 단계)
...

## 4. 상세기능
핵심 로직을 항목별로 작성:
- 유효성 검사 로직
- 주요 SAP 함수/BAPI 사용 계획
- 데이터 처리 로직
- 오류 처리 방안

## 5. 체크포인트
구현 전 고객사와 반드시 확인해야 할 사항:
- (체크포인트 1)
- (체크포인트 2)
- (체크포인트 3)
...

---
위 형식을 그대로 사용하여 마크다운으로 작성하세요."""

    response = model.generate_content(prompt)
    return response.text.strip()
