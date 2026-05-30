"""테스트 계정 소유 요청 — 비테스트 사용자(관리자 제외) 목록·허브 조회 제외."""

from __future__ import annotations

from sqlalchemy import exists
from sqlalchemy.orm import Query, Session

from . import models


def viewer_hides_test_owned_requests(viewer) -> bool:
    """비테스트 뷰어(관리자 제외)는 테스트 계정이 만든 요청을 보지 않음."""
    if not viewer:
        return False
    if getattr(viewer, "is_admin", False):
        return False
    if getattr(viewer, "is_test_account", False):
        return False
    return True


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


def block_test_owned_for_viewer(db: Session, viewer, owner_user_id: int) -> bool:
    if not viewer_hides_test_owned_requests(viewer):
        return False
    return owner_user_is_test_account(db, int(owner_user_id))


def filter_query_exclude_test_owners(q: Query, owner_user_id_column, viewer) -> Query:
    if not viewer_hides_test_owned_requests(viewer):
        return q
    return q.filter(
        ~exists().where(
            models.User.id == owner_user_id_column,
            models.User.is_test_account.is_(True),
        )
    )
