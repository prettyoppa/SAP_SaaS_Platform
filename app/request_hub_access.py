"""Hub/detail read access: consultants see others' requests only if they have an offer (or match) on that request."""

from __future__ import annotations

from sqlalchemy import exists, or_
from sqlalchemy.orm import Query, Session

from . import models


def consultant_has_request_offer(
    db: Session, *, consultant_user_id: int, request_kind: str, request_id: int
) -> bool:
    return (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == consultant_user_id,
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id == request_id,
        )
        .first()
        is not None
    )


def apply_integration_hub_read_access(q: Query, user, *, console_embed: bool = False) -> Query:
    """Narrows an IntegrationRequest query to rows the user may read (hub, embed, status, attachments).

    console_embed: 요청 Console 읽기 전용 iframe — 컨설턴트·관리자는 목록과 동일하게 전체 연동 요청 미리보기.
    """
    if getattr(user, "is_admin", False):
        return q
    if console_embed and getattr(user, "is_consultant", False):
        return q
    ro = models.RequestOffer
    offer_ok = exists().where(
        ro.request_kind == "integration",
        ro.request_id == models.IntegrationRequest.id,
        ro.consultant_user_id == user.id,
    )
    if getattr(user, "is_consultant", False):
        return q.filter(or_(models.IntegrationRequest.user_id == user.id, offer_ok))
    return q.filter(models.IntegrationRequest.user_id == user.id)
