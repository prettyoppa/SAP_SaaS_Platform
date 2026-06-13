"""홈(/) 홍보 팝업용 공지 조회."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models

HOME_POPUP_NOTICE_LIMIT = 2


def _home_popup_notice_query(db: Session):
    return (
        db.query(models.Notice)
        .filter(
            models.Notice.is_active.is_(True),
            models.Notice.show_home_popup.is_(True),
        )
        .order_by(
            models.Notice.sort_order.asc(),
            models.Notice.created_at.desc(),
            models.Notice.id.desc(),
        )
    )


def get_home_popup_notices(
    db: Session,
    *,
    limit: int = HOME_POPUP_NOTICE_LIMIT,
) -> list[models.Notice]:
    """활성 + 홈 팝업 마킹 공지 중 표시 순서·등록일 기준 최대 limit건."""
    if limit < 1:
        return []
    return _home_popup_notice_query(db).limit(limit).all()


def get_home_popup_notice(db: Session) -> models.Notice | None:
    """활성 + 홈 팝업 마킹 공지 중 표시 순서·등록일 기준 1건."""
    return _home_popup_notice_query(db).first()
