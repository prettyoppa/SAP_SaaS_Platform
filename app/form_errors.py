"""HTML 폼 제출 시 FastAPI 검증 오류(422)를 사용자용 문구로 변환."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request

# 필드명 → 한글 (공통)
COMMON_FIELD_LABELS: dict[str, str] = {
    "email": "이메일",
    "password": "비밀번호",
    "full_name": "이름",
    "company": "회사명",
    "verification_code": "인증 코드",
    "title": "제목",
    "content": "내용",
    "source_code": "소스 코드",
    "program_id": "프로그램 ID",
    "transaction_code": "트랜잭션 코드",
    "sap_modules": "SAP 모듈",
    "dev_types": "개발 유형",
    "description": "설명",
    "message_id": "메시지",
    "answers_text": "답변",
    "code": "코드",
    "label_ko": "한국어 라벨",
    "label_en": "영문 라벨",
    "question": "질문",
    "answer": "답변",
    "rating": "평점",
}


def request_accepts_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "text/html" in accept


def safe_back_url(request: Request, default: str = "/") -> str:
    """동일 사이트 Referer만 허용 (오픈 리다이렉트 방지)."""
    ref = request.headers.get("referer")
    if not ref:
        return default
    try:
        r = urlparse(ref)
        b = urlparse(str(request.base_url))
        if r.scheme in ("http", "https") and r.netloc == b.netloc:
            return ref
    except Exception:
        pass
    return default


def humanize_validation_errors(errors: list) -> str:
    """RequestValidationError 의 errors 리스트 → 짧은 한국어 안내."""
    missing: list[str] = []
    extras: list[str] = []

    for e in errors:
        loc = e.get("loc") or ()
        field: str | None = None
        if len(loc) >= 2 and loc[0] in ("body", "query", "path"):
            f = loc[-1]
            field = str(f) if not isinstance(f, int) else None
        elif len(loc) >= 1:
            f = loc[-1]
            field = str(f) if not isinstance(f, int) else None

        label = COMMON_FIELD_LABELS.get(field or "", field or "항목")
        typ = e.get("type") or ""

        if typ == "missing":
            if label not in missing:
                missing.append(label)
        elif typ in ("value_error", "string_too_short", "string_too_long"):
            msg = (e.get("msg") or "").replace("Value error, ", "").strip()
            extras.append(f"{label}: {msg}" if msg else f"{label} 값을 확인해 주세요.")
        else:
            msg = e.get("msg") or "형식이 올바르지 않습니다."
            if field:
                extras.append(f"{label}: {msg}")
            else:
                extras.append(msg)

    parts: list[str] = []
    if missing:
        parts.append("필수 항목을 입력해 주세요: " + ", ".join(missing))
    if extras:
        parts.append(" ".join(extras))
    if not parts:
        parts.append("입력 내용을 확인해 주세요.")
    return " ".join(parts)
