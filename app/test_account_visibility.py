"""테스트 계정 소유 요청 — 비테스트 사용자(관리자 제외) 목록·허브 조회 제외."""

from __future__ import annotations

from sqlalchemy import exists, or_
from sqlalchemy.orm import Query, Session

from . import models

_CONSOLE_SEL_PREFIX_TO_KIND = {
    "rfp": "rfp",
    "ana": "analysis",
    "int": "integration",
}


def viewer_hides_test_owned_requests(viewer) -> bool:
    """비테스트 뷰어(관리자 제외)는 테스트 계정이 만든 요청을 보지 않음."""
    if not viewer:
        return False
    if getattr(viewer, "is_admin", False):
        return False
    if getattr(viewer, "is_test_account", False):
        return False
    return True


def parse_console_sel_key(sel_key: str) -> tuple[str, int] | None:
    raw = (sel_key or "").strip().lower()
    if ":" not in raw:
        return None
    prefix, sid = raw.split(":", 1)
    kind = _CONSOLE_SEL_PREFIX_TO_KIND.get(prefix)
    if not kind:
        return None
    try:
        return kind, int(sid)
    except (TypeError, ValueError):
        return None


def owner_user_is_test_account(db: Session, owner_user_id: int) -> bool:
    return (
        db.query(models.User.id)
        .filter(
            models.User.id == int(owner_user_id),
            models.User.is_test_account.is_(True),
        )
        .first()
        is not None
    )


def is_published_to_consultants(db: Session, request_kind: str, request_id: int) -> bool:
    return (
        db.query(models.RequestConsultantVisibility.id)
        .filter(
            models.RequestConsultantVisibility.request_kind == (request_kind or "").strip(),
            models.RequestConsultantVisibility.request_id == int(request_id),
            models.RequestConsultantVisibility.visible_to_consultants.is_(True),
        )
        .first()
        is not None
    )


def set_published_to_consultants(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    published: bool,
    updated_by_user_id: int | None = None,
) -> None:
    kind = (request_kind or "").strip()
    rid = int(request_id)
    row = (
        db.query(models.RequestConsultantVisibility)
        .filter(
            models.RequestConsultantVisibility.request_kind == kind,
            models.RequestConsultantVisibility.request_id == rid,
        )
        .first()
    )
    if published:
        if row:
            row.visible_to_consultants = True
            if updated_by_user_id is not None:
                row.updated_by_user_id = int(updated_by_user_id)
        else:
            db.add(
                models.RequestConsultantVisibility(
                    request_kind=kind,
                    request_id=rid,
                    visible_to_consultants=True,
                    updated_by_user_id=updated_by_user_id,
                )
            )
    elif row:
        row.visible_to_consultants = False
        if updated_by_user_id is not None:
            row.updated_by_user_id = int(updated_by_user_id)


def block_test_owned_for_viewer(
    db: Session,
    viewer,
    owner_user_id: int,
    *,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> bool:
    if not viewer_hides_test_owned_requests(viewer):
        return False
    if not owner_user_is_test_account(db, int(owner_user_id)):
        return False
    if request_kind is not None and request_id is not None:
        if is_published_to_consultants(db, request_kind, int(request_id)):
            return False
    return True


def filter_query_exclude_test_owners(
    q: Query,
    owner_user_id_column,
    viewer,
    *,
    request_kind: str | None = None,
    request_id_column=None,
) -> Query:
    if not viewer_hides_test_owned_requests(viewer):
        return q
    test_owner = exists().where(
        models.User.id == owner_user_id_column,
        models.User.is_test_account.is_(True),
    )
    if request_kind and request_id_column is not None:
        published = exists().where(
            models.RequestConsultantVisibility.request_kind == request_kind,
            models.RequestConsultantVisibility.request_id == request_id_column,
            models.RequestConsultantVisibility.visible_to_consultants.is_(True),
        )
        return q.filter(or_(~test_owner, published))
    return q.filter(~test_owner)


def enrich_console_row_consultant_publish(db: Session, row: dict, viewer) -> dict:
    """요청 Console 행에 테스트 소유·컨설턴트 공개 메타를 붙임."""
    owner_id = row.get("owner_user_id")
    parsed = parse_console_sel_key(row.get("sel_key") or "")
    if owner_id is None or not parsed:
        return row
    req_kind, req_id = parsed
    owner_is_test = owner_user_is_test_account(db, int(owner_id))
    published = (not owner_is_test) or is_published_to_consultants(db, req_kind, req_id)
    row["owner_is_test_account"] = owner_is_test
    row["consultant_published"] = published
    row["can_toggle_consultant_publish"] = bool(getattr(viewer, "is_admin", False) and owner_is_test)
    return row
