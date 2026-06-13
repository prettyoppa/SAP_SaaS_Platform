"""메뉴 랜딩 페이지(타일·검색) 공통: 분석·연동 버킷과 홈 타일 집계 일관 처리."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, joinedload

from . import models
from .delivered_code_package import (
    delivered_package_has_body,
    integration_delivered_body_ready,
    parse_delivered_code_payload,
)
from .request_hub_access import abap_analysis_consultant_read_scope
from .test_account_visibility import filter_query_exclude_test_owners
from .rfp_landing import (
    BUCKET_ORDER,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    parse_slashed_date,
    rfp_ids_with_interview_messages,
    rfp_landing_bucket,
)

DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO = """요구사항과 ABAP 코드를 제출하면 구조 분석과 요구사항 연계 해석을 제공합니다.

- 프로그램·모듈 맥락과 업무 규칙을 함께 설명하면 분석 정확도가 올라갑니다
- 참고 코드·첨부로 실제 패턴을 공유할 수 있습니다
- 신규 개발 제안까지 이어지는 경우 **신규 개발** 메뉴와 병행해 보실 수 있습니다"""

DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO = """Excel VBA, Python, 소규모 웹앱, 배치, API 연동 등 **SAP와 연결되는 비-ABAP** 과제를 요청합니다.

- SAP 터치포인트(RFC, IDoc, OData 등)와 보안·환경 조건을 적어 주시면 분석에 반영됩니다
- 구현 형태(매크로·스크립트·API 등)를 선택하고 상세 설명을 남겨 주세요"""

__all__ = [
    "BUCKET_ORDER",
    "TILE_ORDER_WITH_ALL",
    "VALID_URL_BUCKETS",
    "parse_slashed_date",
    "standard_menu_bucket_meta",
    "menu_landing_preset_params",
    "menu_landing_url",
    "abap_analysis_menu_bucket",
    "integration_menu_bucket",
    "abap_analysis_menu_aggregate",
    "filtered_abap_analysis_menu_rows",
    "integration_menu_aggregate",
    "filtered_integration_menu_rows",
    "DEFAULT_SERVICE_ANALYSIS_INTRO_MD_KO",
    "DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO",
    "user_proposal_pending_offer_badges",
    "request_ids_with_unmatched_offers_only",
]


def menu_landing_preset_params(qp) -> dict[str, str]:
    m: dict[str, str] = {}
    for k in ("title", "date_from", "date_to"):
        v = qp.get(k)
        if v and str(v).strip():
            m[k] = str(v).strip()
    return m


def menu_landing_url(base_path: str, presets: dict[str, str], bucket: str) -> str:
    m = dict(presets)
    m["bucket"] = bucket
    return base_path + "?" + urlencode(m)


HOME_SERVICE_MENU_PATHS: dict[str, str] = {
    "rfp": "/services/abap",
    "analysis": "/abap-analysis",
    "integration": "/integration",
}


def home_tile_stage_links(channel: str) -> dict[str, str]:
    """홈 서비스 타일 단계 칩 → 메뉴 랜딩과 동일 bucket 필터 URL."""
    base = HOME_SERVICE_MENU_PATHS.get((channel or "").strip().lower(), "/")
    return {k: menu_landing_url(base, {}, k) for k in BUCKET_ORDER}


def standard_menu_bucket_meta() -> dict[str, dict]:
    """신규 개발·분석·연동 랜딩에서 동일한 타일 라벨·아이콘."""
    from .ui_nav_labels import BUCKET_LABEL_EN

    return {
        "all": {
            "label": "전체",
            "label_en": BUCKET_LABEL_EN["all"],
            "icon": "fa-layer-group",
            "fg": "#a78bfa",
            "bg": "rgba(167,139,250,.22)",
            "hint": "모든 진행 상태",
        },
        "delivery": {
            "label": "납품",
            "label_en": BUCKET_LABEL_EN["delivery"],
            "icon": "fa-truck",
            "fg": "#94a3b8",
            "bg": "rgba(148,163,184,.22)",
            "hint": "FS·납품 코드 생성·완료",
        },
        "proposal": {
            "label": "제안",
            "label_en": BUCKET_LABEL_EN["proposal"],
            "icon": "fa-file-lines",
            "fg": "#22c55e",
            "bg": "rgba(34,197,94,.18)",
        },
        "analysis": {
            "label": "분석",
            "label_en": BUCKET_LABEL_EN["analysis"],
            "icon": "fa-magnifying-glass-chart",
            "fg": "#6366f1",
            "bg": "rgba(99,102,241,.18)",
        },
        "in_progress": {
            "label": "진행중",
            "label_en": BUCKET_LABEL_EN["in_progress"],
            "icon": "fa-spinner",
            "fg": "#eab308",
            "bg": "rgba(234,179,8,.2)",
        },
        "draft": {
            "label": "임시저장",
            "label_en": BUCKET_LABEL_EN["draft"],
            "icon": "fa-floppy-disk",
            "fg": "#64748b",
            "bg": "rgba(100,116,139,.2)",
        },
    }


def abap_analysis_menu_bucket(row: models.AbapAnalysisRequest) -> str:
    """홈 타일 분류. 본 레코드(제안·FS·납품·개선)만 사용 — RFP 연결 여부와 무관하게 분석 메뉴에서 분리한다."""
    if row.is_draft:
        return "draft"
    fs_s = ((getattr(row, "fs_status", None) or "none").strip().lower() or "none")
    dc_s = ((getattr(row, "delivered_code_status", None) or "none").strip().lower() or "none")
    dc_ok = dc_s == "ready" and (
        delivered_package_has_body(parse_delivered_code_payload(getattr(row, "delivered_code_payload", None)))
        or (getattr(row, "delivered_code_text", None) or "").strip()
    )
    fs_ok = fs_s == "ready" and (getattr(row, "fs_text", None) or "").strip()
    if dc_ok or fs_ok:
        return "delivery"
    if fs_s == "generating" or dc_s == "generating":
        return "delivery"
    if (getattr(row, "proposal_text", None) or "").strip():
        return "proposal"
    if (getattr(row, "interview_status", None) or "") == "generating_proposal":
        return "proposal"
    if row.is_analyzed:
        return "in_progress"
    return "analysis"


def _integration_request_landing_bucket(
    ir: models.IntegrationRequest, *, has_interview_messages: bool | None = None
) -> str:
    """연동 요청(IntegrationRequest) 본문 필드만으로 단계 분류 — rfp_landing_bucket과 동일 우선순위."""
    fs_s = ((getattr(ir, "fs_status", None) or "none").strip().lower() or "none")
    dc_s = ((getattr(ir, "delivered_code_status", None) or "none").strip().lower() or "none")
    dc_ok = integration_delivered_body_ready(ir)
    fs_ok = fs_s == "ready" and (getattr(ir, "fs_text", None) or "").strip()
    if dc_ok or fs_ok:
        return "delivery"
    if fs_s == "generating" or dc_s == "generating":
        return "delivery"
    if (getattr(ir, "proposal_text", None) or "").strip():
        return "proposal"
    if (getattr(ir, "status", None) or "").lower() == "draft":
        return "draft"
    if (getattr(ir, "interview_status", None) or "") == "generating_proposal":
        return "analysis"
    if has_interview_messages is None:
        msgs = getattr(ir, "interview_messages", None) or []
        has_interview_messages = bool(msgs and len(msgs) > 0)
    if has_interview_messages:
        return "analysis"
    return "in_progress"


def _max_landing_bucket(a: str, b: str) -> str:
    """BUCKET_ORDER 앞쪽이 더 진행된 단계(delivery가 가장 우선)."""
    ia = BUCKET_ORDER.index(a) if a in BUCKET_ORDER else len(BUCKET_ORDER)
    ib = BUCKET_ORDER.index(b) if b in BUCKET_ORDER else len(BUCKET_ORDER)
    return a if ia <= ib else b


def integration_menu_bucket(
    ir: models.IntegrationRequest,
    *,
    has_interview_messages: bool | None = None,
    workflow_rfp: models.RFP | None = None,
    workflow_rfp_has_messages: bool | None = None,
) -> str:
    """
    연동 요청 버킷(RFP 타일 라벨과 동일 이름).
    FS·납품 코드는 연동 요청 레코드에 저장되므로, 과거 RFP 연결이 있어도 IR 단계와 병합한다.
    """
    b_ir = _integration_request_landing_bucket(ir, has_interview_messages=has_interview_messages)
    wr = workflow_rfp if workflow_rfp is not None else getattr(ir, "workflow_rfp", None)
    if wr is not None:
        return _max_landing_bucket(
            b_ir,
            rfp_landing_bucket(wr, has_interview_messages=workflow_rfp_has_messages),
        )
    return b_ir


def _abap_analysis_base_query(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    consultant_matched: bool = False,
    viewer=None,
):
    q = db.query(models.AbapAnalysisRequest)
    if admin:
        q = q.options(joinedload(models.AbapAnalysisRequest.owner))
        if viewer is not None:
            q = filter_query_exclude_test_owners(
                q,
                models.AbapAnalysisRequest.user_id,
                viewer,
                request_kind="analysis",
                request_id_column=models.AbapAnalysisRequest.id,
            )
        return q
    if consultant_matched:
        return q.options(joinedload(models.AbapAnalysisRequest.owner)).filter(
            or_(
                models.AbapAnalysisRequest.user_id == user_id,
                abap_analysis_consultant_read_scope(user_id),
            )
        )
    return q.filter(models.AbapAnalysisRequest.user_id == user_id)


def _apply_abap_analysis_filters(q, *, title_q: str | None, date_from: date | None, date_to: date | None):
    if title_q and str(title_q).strip():
        pat = f"%{str(title_q).strip()}%"
        q = q.filter(
            or_(
                models.AbapAnalysisRequest.title.ilike(pat),
                models.AbapAnalysisRequest.requirement_text.ilike(pat),
            )
        )
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time())
        q = q.filter(models.AbapAnalysisRequest.created_at >= start)
    if date_to is not None:
        end_excl = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        q = q.filter(models.AbapAnalysisRequest.created_at < end_excl)
    return q


def abap_analysis_menu_aggregate(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    consultant_matched: bool = False,
    viewer=None,
) -> tuple[dict[str, int], dict[str, list[models.AbapAnalysisRequest]]]:
    q = _abap_analysis_base_query(
        db,
        admin=admin,
        user_id=user_id,
        consultant_matched=consultant_matched,
        viewer=viewer,
    )
    rows = q.order_by(models.AbapAnalysisRequest.created_at.desc()).all()
    buckets: dict[str, list[models.AbapAnalysisRequest]] = {k: [] for k in BUCKET_ORDER}
    for row in rows:
        b = abap_analysis_menu_bucket(row)
        if b in buckets:
            buckets[b].append(row)
    counts = {k: len(buckets[k]) for k in BUCKET_ORDER}
    return counts, buckets


def filtered_abap_analysis_menu_rows(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    bucket: str,
    title_q: str | None,
    date_from: date | None,
    date_to: date | None,
    consultant_matched: bool = False,
    viewer=None,
) -> list[models.AbapAnalysisRequest]:
    q = _abap_analysis_base_query(
        db,
        admin=admin,
        user_id=user_id,
        consultant_matched=consultant_matched,
        viewer=viewer,
    )
    q = _apply_abap_analysis_filters(q, title_q=title_q, date_from=date_from, date_to=date_to)
    rows = q.order_by(models.AbapAnalysisRequest.created_at.desc()).all()
    if bucket == "all":
        return rows
    return [row for row in rows if abap_analysis_menu_bucket(row) == bucket]


def _integration_base_query(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    consultant_matched: bool = False,
    viewer=None,
):
    q = db.query(models.IntegrationRequest)
    if admin:
        q = q.options(joinedload(models.IntegrationRequest.owner))
        if viewer is not None:
            q = filter_query_exclude_test_owners(
                q,
                models.IntegrationRequest.user_id,
                viewer,
                request_kind="integration",
                request_id_column=models.IntegrationRequest.id,
            )
        return q
    if consultant_matched:
        ro = models.RequestOffer
        return q.options(joinedload(models.IntegrationRequest.owner)).filter(
            or_(
                models.IntegrationRequest.user_id == user_id,
                exists().where(
                    ro.request_kind == "integration",
                    ro.request_id == models.IntegrationRequest.id,
                    ro.consultant_user_id == user_id,
                    ro.status == "matched",
                ),
            )
        )
    return q.filter(models.IntegrationRequest.user_id == user_id)


def _integration_menu_bucket_context(
    db: Session, rows: list[models.IntegrationRequest]
) -> dict[str, object]:
    ir_msg = integration_ids_with_interview_messages(db, [int(r.id) for r in rows])
    wr_ids = list({int(r.workflow_rfp_id) for r in rows if getattr(r, "workflow_rfp_id", None)})
    wr_by_id: dict[int, models.RFP] = {}
    wr_msg: set[int] = set()
    if wr_ids:
        wr_by_id = {
            int(r.id): r for r in db.query(models.RFP).filter(models.RFP.id.in_(wr_ids)).all()
        }
        wr_msg = rfp_ids_with_interview_messages(db, wr_ids)
    return {"ir_msg": ir_msg, "wr_by_id": wr_by_id, "wr_msg": wr_msg}


def _integration_menu_bucket_with_context(
    row: models.IntegrationRequest, ctx: dict[str, object]
) -> str:
    wr = None
    if getattr(row, "workflow_rfp_id", None):
        wr = ctx["wr_by_id"].get(int(row.workflow_rfp_id))  # type: ignore[union-attr]
    wr_msg = ctx["wr_msg"]  # type: ignore[assignment]
    return integration_menu_bucket(
        row,
        has_interview_messages=int(row.id) in ctx["ir_msg"],  # type: ignore[operator]
        workflow_rfp=wr,
        workflow_rfp_has_messages=(int(wr.id) in wr_msg) if wr else None,  # type: ignore[operator]
    )


def _apply_integration_filters(q, *, title_q: str | None, date_from: date | None, date_to: date | None):
    if title_q and str(title_q).strip():
        q = q.filter(models.IntegrationRequest.title.ilike(f"%{str(title_q).strip()}%"))
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time())
        q = q.filter(models.IntegrationRequest.created_at >= start)
    if date_to is not None:
        end_excl = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        q = q.filter(models.IntegrationRequest.created_at < end_excl)
    return q


def integration_menu_aggregate(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    consultant_matched: bool = False,
    viewer=None,
) -> tuple[dict[str, int], dict[str, list[models.IntegrationRequest]]]:
    q = _integration_base_query(
        db,
        admin=admin,
        user_id=user_id,
        consultant_matched=consultant_matched,
        viewer=viewer,
    )
    rows = q.order_by(models.IntegrationRequest.created_at.desc()).all()
    ctx = _integration_menu_bucket_context(db, rows)
    buckets: dict[str, list[models.IntegrationRequest]] = {k: [] for k in BUCKET_ORDER}
    for row in rows:
        b = _integration_menu_bucket_with_context(row, ctx)
        if b in buckets:
            buckets[b].append(row)
    counts = {k: len(buckets[k]) for k in BUCKET_ORDER}
    return counts, buckets


def filtered_integration_menu_rows(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    bucket: str,
    title_q: str | None,
    date_from: date | None,
    date_to: date | None,
    consultant_matched: bool = False,
    viewer=None,
) -> list[models.IntegrationRequest]:
    q = _integration_base_query(
        db,
        admin=admin,
        user_id=user_id,
        consultant_matched=consultant_matched,
        viewer=viewer,
    )
    q = _apply_integration_filters(q, title_q=title_q, date_from=date_from, date_to=date_to)
    rows = q.order_by(models.IntegrationRequest.created_at.desc()).all()
    if bucket == "all":
        return rows
    ctx = _integration_menu_bucket_context(db, rows)
    return [row for row in rows if _integration_menu_bucket_with_context(row, ctx) == bucket]


def request_ids_with_unmatched_offers_only(
    db: Session, request_kind: str, ids: list[int]
) -> set[int]:
    """offered 오퍼는 있으나 matched 오퍼가 없는 요청 ID (빨간점·알림용)."""
    if not ids:
        return set()
    id_list = [int(i) for i in ids]
    offered = {
        int(r[0])
        for r in db.query(models.RequestOffer.request_id)
        .filter(
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id.in_(id_list),
            models.RequestOffer.status == "offered",
        )
        .distinct()
        .all()
        if r and r[0] is not None
    }
    if not offered:
        return set()
    matched = {
        int(r[0])
        for r in db.query(models.RequestOffer.request_id)
        .filter(
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id.in_(id_list),
            models.RequestOffer.status == "matched",
        )
        .distinct()
        .all()
        if r and r[0] is not None
    }
    return offered - matched


def integration_ids_with_interview_messages(db: Session, integration_ids: list[int]) -> set[int]:
    if not integration_ids:
        return set()
    return {
        int(r[0])
        for r in db.query(models.IntegrationInterviewMessage.integration_request_id)
        .filter(
            models.IntegrationInterviewMessage.integration_request_id.in_(
                [int(i) for i in integration_ids]
            )
        )
        .distinct()
        .all()
        if r[0] is not None
    }


def _proposal_bucket_rfp_ids(db: Session, rfps: list[models.RFP]) -> list[int]:
    if not rfps:
        return []
    msg_ids = rfp_ids_with_interview_messages(db, [int(r.id) for r in rfps])
    return [
        int(r.id)
        for r in rfps
        if rfp_landing_bucket(r, has_interview_messages=int(r.id) in msg_ids) == "proposal"
    ]


def _proposal_bucket_integration_ids(db: Session, rows: list[models.IntegrationRequest]) -> list[int]:
    if not rows:
        return []
    ctx = _integration_menu_bucket_context(db, rows)
    return [
        int(ir.id)
        for ir in rows
        if _integration_menu_bucket_with_context(ir, ctx) == "proposal"
    ]


def user_proposal_pending_offer_badges(db: Session, user_id: int) -> dict[str, bool]:
    """본인 소유 '제안' 버킷 요청 중, 매칭 없이 offered 오퍼만 있는 경우 메뉴 빨간점."""

    if not user_id:
        return {"rfp": False, "analysis": False, "integration": False}

    rfps = db.query(models.RFP).filter(models.RFP.user_id == user_id).all()
    rfp_ids = _proposal_bucket_rfp_ids(db, rfps)

    analyses = (
        db.query(models.AbapAnalysisRequest)
        .filter(models.AbapAnalysisRequest.user_id == user_id)
        .all()
    )
    ana_proposal = [r for r in analyses if abap_analysis_menu_bucket(r) == "proposal"]
    ana_rfp_ids = list(
        {int(r.workflow_rfp_id) for r in ana_proposal if getattr(r, "workflow_rfp_id", None)}
    )
    ana_row_ids = [int(r.id) for r in ana_proposal if not getattr(r, "workflow_rfp_id", None)]

    ints = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.user_id == user_id)
        .all()
    )
    int_ids = _proposal_bucket_integration_ids(db, ints)

    def _has(kind: str, ids: list[int]) -> bool:
        return bool(request_ids_with_unmatched_offers_only(db, kind, ids))

    return {
        "rfp": _has("rfp", rfp_ids),
        "analysis": _has("analysis", ana_row_ids) or (_has("rfp", ana_rfp_ids) if ana_rfp_ids else False),
        "integration": _has("integration", int_ids),
    }
