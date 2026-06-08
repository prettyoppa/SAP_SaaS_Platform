"""컨설턴트 → 요청자 납품물(FS·개발코드) 공개 제어."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .code_asset_access import consultant_is_matched_on_request
from .delivered_code_package import integration_delivered_body_ready, rfp_delivered_body_ready
from .request_hub_access import user_can_operate_request_deliverables

_VISIBILITY_POST_PATH = {
    "rfp": "/rfp/{request_id}/delivery/requester-visibility",
    "analysis": "/abap-analysis/{request_id}/delivery/requester-visibility",
    "integration": "/integration/{request_id}/delivery/requester-visibility",
}


def requester_visibility_post_url(*, request_kind: str, request_id: int) -> str:
    kind = (request_kind or "").strip().lower()
    template = _VISIBILITY_POST_PATH.get(kind)
    if not template:
        return ""
    return template.format(request_id=int(request_id))


def visibility_toggle_redirect_url(
    *,
    user,
    owner_user_id: int,
    request_kind: str,
    request_id: int,
    phase: str,
) -> str:
    """POST 후 허브로 돌아갈 URL. 컨설턴트 console-readonly 경로 유지."""
    from .request_hub_access import menu_abap_detail_url, menu_entity_hub_url

    kind = (request_kind or "").strip().lower()
    phase_key = (phase or "fs").strip().lower()
    rid = int(request_id)
    owner_id = int(owner_user_id)

    if kind == "analysis":
        base = menu_abap_detail_url(user=user, owner_user_id=owner_id, request_id=rid)
        return f"{base}?phase={phase_key}#abap-phase-{phase_key}"
    return menu_entity_hub_url(
        user=user,
        owner_user_id=owner_id,
        request_kind=kind if kind == "integration" else "rfp",
        request_id=rid,
        phase=phase_key,
    )


def fs_deliverable_ready(entity: Any | None) -> bool:
    if entity is None:
        return False
    return (getattr(entity, "fs_status", None) or "").strip() == "ready" and bool(
        (getattr(entity, "fs_text", None) or "").strip()
    )


def dev_code_deliverable_ready(entity: Any | None) -> bool:
    if entity is None:
        return False
    kind_hint = type(entity).__name__
    if kind_hint == "IntegrationRequest":
        return integration_delivered_body_ready(entity)
    return rfp_delivered_body_ready(entity)


def reset_fs_requester_visibility(entity: Any) -> None:
    if hasattr(entity, "fs_visible_to_requester"):
        entity.fs_visible_to_requester = False


def reset_dev_code_requester_visibility(entity: Any) -> None:
    if hasattr(entity, "dev_code_visible_to_requester"):
        entity.dev_code_visible_to_requester = False


def owner_is_matched_consultant_on_request(
    db: Session,
    *,
    owner_user_id: int,
    request_kind: str,
    request_id: int,
) -> bool:
    """요청자와 매칭 컨설턴트가 동일 계정(본인 의뢰·본인 납품)인 경우."""
    try:
        owner_id = int(owner_user_id)
    except (TypeError, ValueError):
        return False
    return consultant_is_matched_on_request(
        db,
        consultant_user_id=owner_id,
        request_kind=request_kind,
        request_id=int(request_id),
    )


def _should_auto_release_to_requester(
    db: Session | None,
    entity: Any,
    *,
    request_kind: str | None,
    request_id: int | None,
) -> bool:
    if not db or not request_kind or request_id is None:
        return False
    owner_id = getattr(entity, "user_id", None)
    if owner_id is None:
        return False
    return owner_is_matched_consultant_on_request(
        db,
        owner_user_id=int(owner_id),
        request_kind=request_kind,
        request_id=int(request_id),
    )


def on_fs_generation_succeeded(
    entity: Any,
    *,
    db: Session | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> None:
    if _should_auto_release_to_requester(
        db, entity, request_kind=request_kind, request_id=request_id
    ):
        if hasattr(entity, "fs_visible_to_requester"):
            entity.fs_visible_to_requester = True
    else:
        reset_fs_requester_visibility(entity)


def on_dev_code_generation_succeeded(
    entity: Any,
    *,
    db: Session | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> None:
    if _should_auto_release_to_requester(
        db, entity, request_kind=request_kind, request_id=request_id
    ):
        if hasattr(entity, "dev_code_visible_to_requester"):
            entity.dev_code_visible_to_requester = True
    else:
        reset_dev_code_requester_visibility(entity)


def _is_owner(user, owner_user_id: int) -> bool:
    if not user:
        return False
    try:
        return int(user.id) == int(owner_user_id)
    except (TypeError, ValueError):
        return False


def _viewer_is_admin(user) -> bool:
    return bool(user and getattr(user, "is_admin", False))


def _viewer_is_matched_consultant(
    db: Session, user, *, request_kind: str, request_id: int
) -> bool:
    if not user or not getattr(user, "is_consultant", False):
        return False
    return consultant_is_matched_on_request(
        db,
        consultant_user_id=int(user.id),
        request_kind=request_kind,
        request_id=int(request_id),
    )


def user_can_view_fs_deliverable_content(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    if not user:
        return False
    if _viewer_is_admin(user):
        return True
    if _viewer_is_matched_consultant(db, user, request_kind=request_kind, request_id=request_id):
        return True
    if _is_owner(user, owner_user_id):
        if not fs_deliverable_ready(entity):
            return True
        if owner_is_matched_consultant_on_request(
            db,
            owner_user_id=owner_user_id,
            request_kind=request_kind,
            request_id=request_id,
        ):
            return True
        return bool(getattr(entity, "fs_visible_to_requester", False))
    return False


def user_can_view_dev_code_deliverable_content(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    if not user:
        return False
    if _viewer_is_admin(user):
        return True
    if _viewer_is_matched_consultant(db, user, request_kind=request_kind, request_id=request_id):
        return True
    if _is_owner(user, owner_user_id):
        if not dev_code_deliverable_ready(entity):
            return True
        if owner_is_matched_consultant_on_request(
            db,
            owner_user_id=owner_user_id,
            request_kind=request_kind,
            request_id=request_id,
        ):
            return True
        return bool(getattr(entity, "dev_code_visible_to_requester", False))
    return False


def fs_withheld_from_requester(
    user,
    *,
    owner_user_id: int,
    entity: Any | None,
    db: Session | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> bool:
    if not _is_owner(user, owner_user_id):
        return False
    if db and request_kind and request_id is not None and owner_is_matched_consultant_on_request(
        db,
        owner_user_id=owner_user_id,
        request_kind=request_kind,
        request_id=request_id,
    ):
        return False
    return fs_deliverable_ready(entity) and not bool(getattr(entity, "fs_visible_to_requester", False))


def dev_code_withheld_from_requester(
    user,
    *,
    owner_user_id: int,
    entity: Any | None,
    db: Session | None = None,
    request_kind: str | None = None,
    request_id: int | None = None,
) -> bool:
    if not _is_owner(user, owner_user_id):
        return False
    if db and request_kind and request_id is not None and owner_is_matched_consultant_on_request(
        db,
        owner_user_id=owner_user_id,
        request_kind=request_kind,
        request_id=request_id,
    ):
        return False
    return dev_code_deliverable_ready(entity) and not bool(
        getattr(entity, "dev_code_visible_to_requester", False)
    )


def user_can_toggle_fs_requester_visibility(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    if owner_is_matched_consultant_on_request(
        db,
        owner_user_id=owner_user_id,
        request_kind=request_kind,
        request_id=request_id,
    ):
        return False
    return user_can_operate_request_deliverables(
        db, user, request_kind=request_kind, request_id=request_id
    ) and fs_deliverable_ready(entity)


def user_can_toggle_dev_code_requester_visibility(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    if owner_is_matched_consultant_on_request(
        db,
        owner_user_id=owner_user_id,
        request_kind=request_kind,
        request_id=request_id,
    ):
        return False
    return user_can_operate_request_deliverables(
        db, user, request_kind=request_kind, request_id=request_id
    ) and dev_code_deliverable_ready(entity)


def user_may_download_fs_assets(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    return user_can_view_fs_deliverable_content(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    ) and fs_deliverable_ready(entity)


def user_may_download_dev_code_assets(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    entity: Any | None,
) -> bool:
    return user_can_view_dev_code_deliverable_content(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    ) and dev_code_deliverable_ready(entity)


def apply_requester_visibility_toggle(
    db: Session,
    user,
    *,
    entity: Any,
    request_kind: str,
    request_id: int,
    stage: str,
    visible: bool,
) -> str | None:
    """Returns error message or None on success."""
    owner_id = getattr(entity, "user_id", None)
    if owner_id is not None and owner_is_matched_consultant_on_request(
        db,
        owner_user_id=int(owner_id),
        request_kind=request_kind,
        request_id=request_id,
    ):
        return "forbidden"
    stage_key = (stage or "").strip().lower()
    if stage_key == "fs":
        if not user_can_toggle_fs_requester_visibility(
            db,
            user,
            request_kind=request_kind,
            request_id=request_id,
            owner_user_id=int(owner_id),
            entity=entity,
        ):
            return "forbidden"
        entity.fs_visible_to_requester = bool(visible)
    elif stage_key in ("devcode", "dev_code", "dc"):
        if not user_can_toggle_dev_code_requester_visibility(
            db,
            user,
            request_kind=request_kind,
            request_id=request_id,
            owner_user_id=int(owner_id),
            entity=entity,
        ):
            return "forbidden"
        entity.dev_code_visible_to_requester = bool(visible)
    else:
        return "invalid_stage"
    db.commit()
    return None
