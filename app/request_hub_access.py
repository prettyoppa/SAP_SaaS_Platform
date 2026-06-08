"""Hub/detail read access: consultants see others' requests only if they have an offer (or match) on that request."""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, or_
from sqlalchemy.orm import Query, Session

from . import models
from .paid_tier import paid_delivery_pipeline_started, user_can_operate_delivery
from .test_account_visibility import block_test_owned_for_viewer, filter_query_exclude_test_owners
from .request_offer_lifecycle import OFFER_STATUS_MATCHED, OFFER_STATUS_OFFERED


def abap_analysis_consultant_matched_on_linked_rfp(user_id: int):
    """AbapAnalysisRequest에 대해: 연결된 신규개발(RFP)에 컨설턴트 매칭 오퍼가 있으면 True (exists)."""
    ro = models.RequestOffer
    return exists().where(
        models.AbapAnalysisRequest.workflow_rfp_id.isnot(None),
        ro.request_kind == "rfp",
        ro.request_id == models.AbapAnalysisRequest.workflow_rfp_id,
        ro.consultant_user_id == user_id,
        ro.status == "matched",
    )


def abap_analysis_consultant_matched_on_row(user_id: int):
    """분석·개선 요청 본건에 request_kind=analysis 매칭 오퍼가 있으면 True."""
    ro = models.RequestOffer
    return exists().where(
        ro.request_kind == "analysis",
        ro.request_id == models.AbapAnalysisRequest.id,
        ro.consultant_user_id == user_id,
        ro.status == "matched",
    )


def abap_analysis_consultant_read_scope(user_id: int):
    """컨설턴트가 타인 분석 건을 볼 수 있는 조건: 본건 매칭 또는 (레거시) 연결 RFP 매칭."""
    return or_(
        abap_analysis_consultant_matched_on_row(user_id),
        abap_analysis_consultant_matched_on_linked_rfp(user_id),
    )


def consultant_has_request_offer(
    db: Session, *, consultant_user_id: int, request_kind: str, request_id: int
) -> bool:
    return (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == consultant_user_id,
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id == request_id,
            models.RequestOffer.status.in_((OFFER_STATUS_OFFERED, OFFER_STATUS_MATCHED)),
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


def user_can_view_request_deliverables(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    paid_entity: Any | None = None,
) -> bool:
    """FS·개발코드 납품 조회: 요청자(결제/파이프라인 규칙), 매칭 컨설턴트, 관리자만."""
    if not user:
        return False
    if block_test_owned_for_viewer(
        db,
        user,
        int(owner_user_id),
        request_kind=request_kind,
        request_id=int(request_id),
    ):
        return False
    if getattr(user, "is_admin", False):
        return True
    try:
        uid = int(user.id)
        owner_id = int(owner_user_id)
    except (TypeError, ValueError):
        return False
    if uid == owner_id:
        if paid_entity is not None and paid_delivery_pipeline_started(paid_entity):
            return True
        return request_has_matched_offer(
            db, request_kind=request_kind, request_id=int(request_id)
        )
    if getattr(user, "is_consultant", False):
        return consultant_is_matched_on_request(
            db,
            consultant_user_id=uid,
            request_kind=request_kind,
            request_id=int(request_id),
        )
    return False


def user_can_operate_request_deliverables(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
) -> bool:
    """FS·납품 코드 생성/첨부: 관리자 또는 해당 요청에 매칭된 컨설턴트."""
    if not user_can_operate_delivery(user):
        return False
    if getattr(user, "is_admin", False):
        return True
    if not getattr(user, "is_consultant", False):
        return False
    return consultant_is_matched_on_request(
        db,
        consultant_user_id=int(user.id),
        request_kind=request_kind,
        request_id=int(request_id),
    )


_FS_MASK_KEYS = (
    "fs_html",
    "ana_fs_html",
    "fs_supplements",
)
_DC_MASK_KEYS = (
    "delivered_code_html",
    "delivered_impl_guide_html",
    "delivered_test_scenarios_html",
    "delivered_package",
    "has_delivered_preview",
    "ana_has_delivered_zip",
)
_DELIVERABLES_MASK_KEYS = _FS_MASK_KEYS + _DC_MASK_KEYS


def apply_hub_deliverables_visibility(
    ctx: dict,
    *,
    db: Session,
    user,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    paid_entity: Any | None,
) -> None:
    """허브 템플릿용 can_view_deliverables / can_operate_delivery 및 민감 필드 마스킹."""
    from .request_deliverables_release import (
        dev_code_deliverable_ready,
        dev_code_withheld_from_requester,
        fs_deliverable_ready,
        fs_withheld_from_requester,
        owner_is_matched_consultant_on_request,
        requester_visibility_post_url,
        user_can_toggle_dev_code_requester_visibility,
        user_can_toggle_fs_requester_visibility,
        user_can_view_dev_code_deliverable_content,
        user_can_view_fs_deliverable_content,
    )

    entity = paid_entity
    can_view = user_can_view_request_deliverables(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        paid_entity=paid_entity,
    )
    can_operate = user_can_operate_request_deliverables(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
    )
    can_view_fs = user_can_view_fs_deliverable_content(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    )
    can_view_dc = user_can_view_dev_code_deliverable_content(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    )
    ctx["can_view_deliverables"] = can_view
    ctx["can_view_fs"] = can_view_fs
    ctx["can_view_dev_code"] = can_view_dc
    ctx["can_operate_delivery"] = can_operate
    visibility_locked = owner_is_matched_consultant_on_request(
        db,
        owner_user_id=owner_user_id,
        request_kind=request_kind,
        request_id=request_id,
    )
    ctx["requester_visibility_locked"] = visibility_locked
    ctx["fs_withheld_from_requester"] = fs_withheld_from_requester(
        user,
        owner_user_id=owner_user_id,
        entity=entity,
        db=db,
        request_kind=request_kind,
        request_id=request_id,
    )
    ctx["dev_code_withheld_from_requester"] = dev_code_withheld_from_requester(
        user,
        owner_user_id=owner_user_id,
        entity=entity,
        db=db,
        request_kind=request_kind,
        request_id=request_id,
    )
    ctx["fs_visible_to_requester"] = True if visibility_locked else bool(
        getattr(entity, "fs_visible_to_requester", False)
    )
    ctx["dev_code_visible_to_requester"] = True if visibility_locked else bool(
        getattr(entity, "dev_code_visible_to_requester", False)
    )
    can_toggle_fs = user_can_toggle_fs_requester_visibility(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    )
    can_toggle_dc = user_can_toggle_dev_code_requester_visibility(
        db,
        user,
        request_kind=request_kind,
        request_id=request_id,
        owner_user_id=owner_user_id,
        entity=entity,
    )
    ctx["can_toggle_fs_requester_visibility"] = can_toggle_fs
    ctx["can_toggle_dev_code_requester_visibility"] = can_toggle_dc
    ctx["show_fs_requester_visibility_control"] = can_toggle_fs or (
        visibility_locked and fs_deliverable_ready(entity)
    )
    ctx["show_dev_code_requester_visibility_control"] = can_toggle_dc or (
        visibility_locked and dev_code_deliverable_ready(entity)
    )
    ctx["requester_visibility_post_url"] = requester_visibility_post_url(
        request_kind=request_kind, request_id=int(request_id)
    )
    ctx["fs_code_asset_unlocked"] = can_view_fs
    ctx["dc_code_asset_unlocked"] = can_view_dc
    ent = ctx.get("as_built_entry_dict") or {}
    ctx["as_built_section_visible"] = bool(ent.get("path"))

    def _mask_keys(keys: tuple[str, ...]) -> None:
        for key in keys:
            if key not in ctx:
                continue
            if key == "delivered_package":
                ctx[key] = None
            elif key == "fs_supplements":
                ctx[key] = []
            elif key.startswith("has_") or key.startswith("ana_has_"):
                ctx[key] = False
            elif "html" in key:
                ctx[key] = ""
            else:
                ctx[key] = None

    if not can_view_fs:
        _mask_keys(_FS_MASK_KEYS)
    if not can_view_dc:
        _mask_keys(_DC_MASK_KEYS)
    if can_view:
        return
    ctx["as_built_entry_dict"] = {}
    ctx["as_built_can_upload"] = False
    _mask_keys(_DELIVERABLES_MASK_KEYS)
    ctx["fs_busy"] = False
    ctx["dc_busy"] = False
    ctx["gen_busy"] = False
    ctx["ana_fs_busy"] = False
    ctx["ana_dc_busy"] = False
    ctx["ana_gen_busy"] = False


def request_has_matched_offer(db: Session, *, request_kind: str, request_id: int) -> bool:
    """요청에 status=matched 오퍼가 하나라도 있으면 True."""
    kind = (request_kind or "").strip().lower()
    return (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.request_kind == kind,
            models.RequestOffer.request_id == int(request_id),
            models.RequestOffer.status == "matched",
        )
        .first()
        is not None
    )


def batch_matched_request_ids(
    db: Session, *, request_kind: str, request_ids: list[int]
) -> set[int]:
    """목록 화면용 — 매칭된 request_id 집합."""
    kind = (request_kind or "").strip().lower()
    ids = [int(x) for x in request_ids if x]
    if not ids:
        return set()
    rows = (
        db.query(models.RequestOffer.request_id)
        .filter(
            models.RequestOffer.request_kind == kind,
            models.RequestOffer.request_id.in_(ids),
            models.RequestOffer.status == "matched",
        )
        .distinct()
        .all()
    )
    return {int(r[0]) for r in rows}


def user_may_use_request_ai_inquiry(
    db: Session,
    user,
    *,
    request_owner_id: int,
    request_kind: str,
    request_id: int,
) -> bool:
    """요청자·관리자·해당 건 오퍼/매칭 컨설턴트 AI에게 문의 패널 사용."""
    if not user:
        return False
    if getattr(user, "is_admin", False):
        return True
    if int(user.id) == int(request_owner_id):
        return True
    if getattr(user, "is_consultant", False) and consultant_has_request_offer(
        db,
        consultant_user_id=int(user.id),
        request_kind=request_kind,
        request_id=int(request_id),
    ):
        return True
    return False


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
    ro = models.RequestOffer
    offer_ok = exists().where(
        ro.request_kind == "integration",
        ro.request_id == models.IntegrationRequest.id,
        ro.consultant_user_id == user.id,
    )
    if console_embed and getattr(user, "is_consultant", False):
        q = q
    elif getattr(user, "is_consultant", False):
        q = q.filter(or_(models.IntegrationRequest.user_id == user.id, offer_ok))
    else:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    return filter_query_exclude_test_owners(
        q,
        models.IntegrationRequest.user_id,
        user,
        request_kind="integration",
        request_id_column=models.IntegrationRequest.id,
    )
