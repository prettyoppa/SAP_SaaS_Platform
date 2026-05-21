"""신규개발·분석·연동·FS·제안서 첨부 — 허용 확장자·구형 Office 거부."""

from __future__ import annotations

import os

# 요청·FS·제안서 첨부 공통 (최종 납품 as-built ZIP 등은 별도)
REQUEST_ATTACHMENT_EXTENSIONS = frozenset({
    ".md",
    ".pdf",
    ".xlsx",
    ".docx",
    ".pptx",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
})

IMAGE_ATTACHMENT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

# 구형 바이너리 Office — 업로드 거부 + 변환 안내
LEGACY_OFFICE_EXTENSIONS = frozenset({".doc", ".xls", ".ppt"})

_LEGACY_ERR_BY_EXT = {
    ".doc": "legacy_office_doc",
    ".xls": "legacy_office_xls",
    ".ppt": "legacy_office_ppt",
}


def attachment_extension_key(filename: str) -> str:
    return os.path.splitext((filename or "").strip())[1].lower()


def upload_attachment_error_key(filename: str) -> str | None:
    """
    업로드 전 확장자 검사.
    None = 허용, 그 외 = 템플릿 error 키 (invalid_file | legacy_office_*).
    """
    ext = attachment_extension_key(filename)
    if not ext:
        return "invalid_file"
    if ext in LEGACY_OFFICE_EXTENSIONS:
        return _LEGACY_ERR_BY_EXT.get(ext, "legacy_office_doc")
    if ext not in REQUEST_ATTACHMENT_EXTENSIONS:
        return "invalid_file"
    return None


def html_accept_extensions() -> str:
    return ",".join(sorted(REQUEST_ATTACHMENT_EXTENSIONS))
