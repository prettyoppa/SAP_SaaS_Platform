"""컨설턴트 FS·납품 코드 삭제 — 요청자 삭제 차단 해제용."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from . import r2_storage
from .delivery_fs_supplements import list_delivery_fs_supplements
from .request_offer_lifecycle import load_request_row


def _delete_supplement_blob(stored_path: str) -> None:
    r2_storage.delete_if_r2_uri(stored_path)
    if (stored_path or "").startswith("r2://"):
        return
    try:
        if stored_path and os.path.isfile(stored_path):
            os.remove(stored_path)
    except OSError:
        pass


def clear_fs_deliverable(db: Session, request_kind: str, request_id: int) -> tuple[bool, str | None]:
    """
    에이전트 FS·첨부·텍스트 보완을 제거하고 fs_status를 none으로 되돌린다.
    generating 중이면 err=fs_generating.
    """
    row = load_request_row(db, request_kind, request_id)
    if row is None:
        return False, "not_found"
    if (getattr(row, "fs_status", None) or "").strip() == "generating":
        return False, "fs_generating"
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    for sup in list_delivery_fs_supplements(db, kind, rid):
        _delete_supplement_blob(sup.stored_path or "")
        db.delete(sup)
    row.fs_text = None
    row.fs_status = "none"
    row.fs_error = None
    row.fs_generated_at = None
    row.fs_job_log = None
    row.fs_consultant_addendum = None
    if hasattr(row, "fs_codegen_supplement_id"):
        row.fs_codegen_supplement_id = None
    db.commit()
    return True, None


def clear_delivered_code_deliverable(
    db: Session, request_kind: str, request_id: int
) -> tuple[bool, str | None]:
    """납품 코드(ABAP·연동 산출물)만 제거."""
    row = load_request_row(db, request_kind, request_id)
    if row is None:
        return False, "not_found"
    if (getattr(row, "delivered_code_status", None) or "").strip() == "generating":
        return False, "devcode_generating"
    from .delivery_workspace import clear_delivered_code_working_copy

    clear_delivered_code_working_copy(row)
    row.delivered_code_status = "none"
    row.delivered_code_text = None
    row.delivered_code_payload = None
    row.delivered_code_generated_at = None
    row.delivered_code_error = None
    row.delivered_job_log = None
    db.commit()
    return True, None


def entity_has_fs_deliverable_content(row) -> bool:
    """FS 납품물(에이전트 본문·첨부·보완 텍스트·비-none 상태) 존재."""
    if row is None:
        return False
    if (getattr(row, "fs_text", None) or "").strip():
        return True
    if (getattr(row, "fs_consultant_addendum", None) or "").strip():
        return True
    fs_st = (getattr(row, "fs_status", None) or "").strip()
    if fs_st in ("ready", "generating", "failed"):
        return True
    return False
