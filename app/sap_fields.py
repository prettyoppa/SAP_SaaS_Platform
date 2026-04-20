"""SAP 프로그램 ID·트랜잭션 코드 입력 검증 (RFP·코드 라이브러리 공통)."""
from __future__ import annotations

import re

# 한글·일본어·중국어 등 IME 입력 차단(서버에서 명시적으로 검사)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")

# 인쇄 가능 ASCII(공백 제외): 영문·숫자·기호 허용
_PRINTABLE_ASCII = re.compile(r"^[!-~]+$")


def validate_program_id(raw: str, *, required: bool, max_len: int = 40) -> tuple[str | None, str | None]:
    """
    Returns (normalized_value, error_key).
    error_key: required | too_long | no_ime_chars | invalid_chars
    """
    v = (raw or "").strip()
    if not v:
        return (None, "required" if required else None)
    if len(v) > max_len:
        return (None, "too_long")
    if _CJK_RE.search(v):
        return (None, "no_ime_chars")
    if not _PRINTABLE_ASCII.match(v):
        return (None, "invalid_chars")
    return (v, None)


def validate_transaction_code(raw: str, *, max_len: int = 20) -> tuple[str | None, str | None]:
    """선택 필드. 빈 값이면 (None, None)."""
    v = (raw or "").strip()
    if not v:
        return (None, None)
    if len(v) > max_len:
        return (None, "too_long")
    if _CJK_RE.search(v):
        return (None, "no_ime_chars")
    if not _PRINTABLE_ASCII.match(v):
        return (None, "invalid_chars")
    return (v, None)
