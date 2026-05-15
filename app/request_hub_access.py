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


def consultant_menu_matched_scope(user) -> bool:
    """메뉴 랜딩·홈 타일: 컨설턴트는 본인 건 + 매칭(matched) 오퍼 건만 집계."""
    return bool(getattr(user, "is_consultant", False) and not getattr(user, "is_admin", False))


def consultant_views_client_request_via_console(user, owner_user_id: int) -> bool:
    """컨설턴트가 타인 소유 매칭 건을 메뉴에서 열 때 읽기 전용 허브 URL."""
    if not consultant_menu_matched_scope(user):
        return False
    try:
        return int(getattr(user, "id", 0)) != int(owner_user_id)
    except (TypeError, ValueError):
        return True


def menu_entity_hub_url(
    *,
    user,
    owner_user_id: int,
    request_kind: str,
    request_id: int,
    phase: str,
    view_summary: bool = False,
) -> str:
    """신규·연동 허브 phase 링크. 컨설턴트+타인 건은 console-readonly."""
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    use_ro = consultant_views_client_request_via_console(user, owner_user_id)

    if kind == "integration":
        from .integration_hub import normalize_integration_hub_phase

        p = normalize_integration_hub_phase(phase)
        base = f"/integration/{rid}/console-readonly" if use_ro else f"/integration/{rid}"
    else:
        from .rfp_hub import normalize_rfp_hub_phase

        p = normalize_rfp_hub_phase(phase)
        base = f"/rfp/{rid}/console-readonly" if use_ro else f"/rfp/{rid}"

    url = f"{base}?phase={p}"
    if view_summary and p == "interview":
        url += "&view=summary"
    return url


def menu_abap_detail_url(*, user, owner_user_id: int, request_id: int, draft: bool = False) -> str:
    """분석·개선 상세. 컨설턴트+타인 건은 console-readonly."""
    rid = int(request_id)
    if draft and not consultant_views_client_request_via_console(user, owner_user_id):
        return f"/abap-analysis/{rid}/edit"
    if consultant_views_client_request_via_console(user, owner_user_id):
        return f"/abap-analysis/{rid}/console-readonly"
    return f"/abap-analysis/{rid}"


def consultant_is_matched_on_request(
    db: Session, *, consultant_user_id: int, request_kind: str, request_id: int
) -> bool:
    """해당 요청에 이 컨설턴트가 매칭된 오퍼가 있으면 True."""
    return (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == int(consultant_user_id),
            models.RequestOffer.request_kind == (request_kind or "").strip().lower(),
            models.RequestOffer.request_id == int(request_id),
            models.RequestOffer.status == "matched",
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
