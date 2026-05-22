"""요청 폼 공통 — 필수 항목 누락·본문 평문 검증."""

from __future__ import annotations

from .rfp_form_suggest import MIN_RFP_DESCRIPTION_CHARS
from .requirement_rich_text import html_to_plain_text, is_html_format

CORE_FIELDS_INCOMPLETE_ERROR = "core_fields_incomplete"


def description_plain_for_validate(description: str, desc_fmt: str) -> str:
    raw = description or ""
    fmt = (desc_fmt or "html").strip().lower()
    if is_html_format(fmt):
        return html_to_plain_text(raw).strip()
    return raw.strip()


def integration_missing_core_field_labels(
    title: str,
    impl_types: list,
    description_plain: str,
    *,
    min_description_chars: int | None = None,
) -> list[str]:
    """연동 요청 임시저장·제출 공통 필수."""
    min_chars = (
        min_description_chars
        if min_description_chars is not None
        else MIN_RFP_DESCRIPTION_CHARS
    )
    miss: list[str] = []
    if not (title or "").strip():
        miss.append("요청 제목")
    if not impl_types:
        miss.append("구현 형태(1개 이상)")
    if len((description_plain or "").strip()) < min_chars:
        miss.append(f"상세 설명(공백 제외 {min_chars}자 이상)")
    return miss
