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


def draft_save_title_only_missing(title: str, *, field_label: str = "요청 제목") -> list[str]:
    """임시저장 시 제목(또는 동등 필드)만 필수."""
    if not (title or "").strip():
        return [field_label]
    return []


def rfp_missing_core_field_labels(
    title: str,
    program_id: str,
    sap_modules: list,
    dev_types: list,
    description: str,
    min_description_chars: int | None = None,
    *,
    draft_minimal: bool = False,
    sap_system_version: str = "",
    sap_system_version_note: str = "",
    require_sap_system_version: bool = True,
) -> list[str]:
    """신규개발·분석개선 — 제출 시 전체 필수, 임시저장은 제목만."""
    from .sap_system_version import sap_system_version_missing_labels

    if draft_minimal:
        return draft_save_title_only_missing(title)

    min_chars = (
        min_description_chars
        if min_description_chars is not None
        else MIN_RFP_DESCRIPTION_CHARS
    )
    miss: list[str] = []
    if not (title or "").strip():
        miss.append("요청 제목")
    if not (program_id or "").strip():
        miss.append("프로그램 ID")
    if not sap_modules:
        miss.append("SAP 모듈(1개 이상)")
    if not dev_types:
        miss.append("개발 유형(1개 이상)")
    miss.extend(
        sap_system_version_missing_labels(
            sap_system_version,
            sap_system_version_note,
            required=require_sap_system_version,
        )
    )
    if len((description or "").strip()) < min_chars:
        miss.append(f"요구사항 자유 기술(공백 제외 {min_chars}자 이상)")
    return miss


def integration_missing_core_field_labels(
    title: str,
    impl_types: list,
    description_plain: str,
    *,
    min_description_chars: int | None = None,
    draft_minimal: bool = False,
) -> list[str]:
    """연동개발 — 제출 시 전체 필수, 임시저장은 요청 제목만."""
    if draft_minimal:
        return draft_save_title_only_missing(title)

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
