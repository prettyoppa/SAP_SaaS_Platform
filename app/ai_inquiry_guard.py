"""
회원 → AI 문의 채널: 프롬프트 인젝션·내부 시스템 탐문 완화(Heuristic).

완전 차단은 불가능하며, LLM 출력은 텍스트일 뿐 서버 코드를 직접 실행하지 않는다.
운영 시에는 WAF·레이트 리밋·로그 모니터·모델 제공사 안전 필터를 병행하는 것을 권장한다.
"""

from __future__ import annotations

import re

# 소문자 정규화 후 부분 일치(과탐지 줄이려 짧은 키워드는 문맥과 함께 쓰지 않음)
_BLOCKED_SNIPPETS_KO_EN = [
    "system prompt",
    "시스템 프롬프트",
    "ignore previous",
    "이전 지시",
    "jailbreak",
    "dan mode",
    ".env",
    "환경변수 목록",
    "google_api_key",
    "openai_api_key",
    "stripe_secret",
    "aws_secret",
    "관리자 패널",
    "admin panel",
    "sql injection",
    "드롭 테이블",
    "drop table",
    "os.system",
    "subprocess",
    "eval(",
    "__import__",
    "pickle.loads",
]

_PUBLIC_REFUSAL_KO = (
    "보안 및 서비스 운영을 위해, 내부 시스템·관리 기능·자격 증명·실행 가능한 코드 조작 요청 등은 "
    "이 채널에서 다루지 않습니다. 작성 중인 요청·분석·연동 내용과 관련된 질문으로 다시 적어 주세요."
)


def check_ai_inquiry_user_text(text: str) -> str | None:
    """
    차단 시 한글 안내 문구 반환, 허용 시 None.
    """
    s = (text or "").strip()
    if not s:
        return None
    low = s.lower()
    for frag in _BLOCKED_SNIPPETS_KO_EN:
        if frag in low:
            return _PUBLIC_REFUSAL_KO
    # 연속 @ 또는 과도한 URL(피싱·데이터 유출 유도) 완화
    if s.count("http://") + s.count("https://") > 8:
        return _PUBLIC_REFUSAL_KO
    if re.search(r"password\s*[:=]", low) or re.search(r"비밀번호\s*[:=]", s):
        return _PUBLIC_REFUSAL_KO
    return None


def ai_inquiry_model_policy_footer() -> str:
    """각 Gemini 프롬프트 끝에 덧붙이는 고정 정책(한국어)."""
    return (
        "\n\n[플랫폼 응답 정책 — 반드시 준수]\n"
        "- 이 서비스의 내부 구현·소스 저장소·관리자(Admin) 기능·API 키·환경 변수·보안 설정에 대한 "
        "설명·추측·나열을 하지 않는다. 요청되면 정중히 거절한다.\n"
        "- 사용자가 서버에서 코드를 실행하거나 파일을 바꾸게 하는 방법은 안내하지 않는다. "
        "ABAP·설정 변경은 일반적인 모범 사례 수준의 설명만 하며, 고객 시스템에 직접 적용하는 명령은 제시하지 않는다.\n"
        "- 자격 증명·토큰·개인정보를 답에 재사용하거나 외부로 유도하지 않는다.\n"
    )
