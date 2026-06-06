"""SE38 납품 작업실 — 요청 헤더(제목·ID·유형) 표시."""

from __future__ import annotations

from typing import Any

from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP


def workspace_enabled_for_kind(request_kind: str) -> bool:
    """SE38 납품 작업실 — 폐쇄. 로컬 IDE(Cursor 등)에서 ZIP으로 작업."""
    _ = request_kind
    return False


def workspace_page_header(entity: Any, request_kind: str) -> dict[str, str]:
    """허브 proposal-header 와 동일한 메타."""
    k = (request_kind or "").strip().lower()
    title = (getattr(entity, "title", None) or "").strip()
    if k == KIND_RFP:
        return {
            "workspace_header_title": title or "신규 개발 요청",
            "workspace_request_no_prefix": "RFP",
            "workspace_kind_tag_ko": "신규 개발",
            "workspace_kind_tag_en": "New development",
            "workspace_header_icon": "fa-code",
            "workspace_header_icon_style": (
                "background:rgba(34,197,94,.15);border-color:rgba(34,197,94,.3);color:#22c55e"
            ),
        }
    if k == KIND_ANALYSIS:
        return {
            "workspace_header_title": title or "SAP ABAP 분석·개선",
            "workspace_request_no_prefix": "ANA",
            "workspace_kind_tag_ko": "분석·개선",
            "workspace_kind_tag_en": "Analysis & improvement",
            "workspace_header_icon": "fa-hospital",
            "workspace_header_icon_style": (
                "background:rgba(99,102,241,.15);border-color:rgba(99,102,241,.3);"
                "color:var(--primary-light)"
            ),
        }
    return {
        "workspace_header_title": title or "요청",
        "workspace_request_no_prefix": "REQ",
        "workspace_kind_tag_ko": "",
        "workspace_kind_tag_en": "",
        "workspace_header_icon": "fa-code",
        "workspace_header_icon_style": "",
    }
