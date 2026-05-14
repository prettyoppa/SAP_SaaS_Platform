"""메뉴 랜딩 페이지(타일·검색) 공통: 분석·연동 버킷과 홈 타일 집계 일관 처리."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from . import models
from .delivered_code_package import rfp_delivered_body_ready
from .rfp_landing import (
    BUCKET_ORDER,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    parse_slashed_date,
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


def standard_menu_bucket_meta() -> dict[str, dict]:
    """신규 개발·분석·연동 랜딩에서 동일한 타일 라벨·아이콘."""
    return {
        "all": {
            "label": "전체",
            "icon": "fa-layer-group",
            "fg": "#a78bfa",
            "bg": "rgba(167,139,250,.22)",
            "hint": "모든 진행 상태",
        },
        "delivery": {
            "label": "납품",
            "icon": "fa-truck",
            "fg": "#94a3b8",
            "bg": "rgba(148,163,184,.22)",
            "hint": "FS·납품 코드 생성·완료",
        },
        "proposal": {"label": "제안", "icon": "fa-file-lines", "fg": "#22c55e", "bg": "rgba(34,197,94,.18)"},
        "analysis": {"label": "분석", "icon": "fa-magnifying-glass-chart", "fg": "#6366f1", "bg": "rgba(99,102,241,.18)"},
        "in_progress": {"label": "진행중", "icon": "fa-spinner", "fg": "#eab308", "bg": "rgba(234,179,8,.2)"},
        "draft": {"label": "임시저장", "icon": "fa-floppy-disk", "fg": "#64748b", "bg": "rgba(100,116,139,.2)"},
    }


def abap_analysis_menu_bucket(row: models.AbapAnalysisRequest) -> str:
    """홈 타일 분류와 동일. 연결 RFP가 있으면 그 진행(납품·제안 등)을 따름."""
    wr = getattr(row, "workflow_rfp", None)
    if wr is not None:
        return rfp_landing_bucket(wr)
    if row.is_draft:
        return "draft"
    if row.is_analyzed:
        return "in_progress"
    return "analysis"


def _integration_request_landing_bucket(ir: models.IntegrationRequest) -> str:
    """연동 요청(IntegrationRequest) 본문 필드만으로 단계 분류 — rfp_landing_bucket과 동일 우선순위."""
    fs_s = ((getattr(ir, "fs_status", None) or "none").strip().lower() or "none")
    dc_s = ((getattr(ir, "delivered_code_status", None) or "none").strip().lower() or "none")
    dc_ok = rfp_delivered_body_ready(ir)
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
    msgs = getattr(ir, "interview_messages", None) or []
    if msgs and len(msgs) > 0:
        return "analysis"
    return "in_progress"


def _max_landing_bucket(a: str, b: str) -> str:
    """BUCKET_ORDER 앞쪽이 더 진행된 단계(delivery가 가장 우선)."""
    ia = BUCKET_ORDER.index(a) if a in BUCKET_ORDER else len(BUCKET_ORDER)
    ib = BUCKET_ORDER.index(b) if b in BUCKET_ORDER else len(BUCKET_ORDER)
    return a if ia <= ib else b


def integration_menu_bucket(ir: models.IntegrationRequest) -> str:
    """
    연동 요청 버킷(RFP 타일 라벨과 동일 이름).
    FS·납품 코드는 연동 요청 레코드에 저장되므로, 과거 RFP 연결이 있어도 IR 단계와 병합한다.
    """
    b_ir = _integration_request_landing_bucket(ir)
    wr = getattr(ir, "workflow_rfp", None)
    if wr is not None:
        return _max_landing_bucket(b_ir, rfp_landing_bucket(wr))
    return b_ir


def _abap_analysis_base_query(db: Session, *, admin: bool, user_id: int):
    q = (
        db.query(models.AbapAnalysisRequest)
        .options(
            joinedload(models.AbapAnalysisRequest.owner),
            joinedload(models.AbapAnalysisRequest.workflow_rfp).joinedload(models.RFP.messages),
        )
    )
    if admin:
        return q
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
    db: Session, *, admin: bool, user_id: int
) -> tuple[dict[str, int], dict[str, list[models.AbapAnalysisRequest]]]:
    q = _abap_analysis_base_query(db, admin=admin, user_id=user_id)
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
) -> list[models.AbapAnalysisRequest]:
    q = _abap_analysis_base_query(db, admin=admin, user_id=user_id)
    q = _apply_abap_analysis_filters(q, title_q=title_q, date_from=date_from, date_to=date_to)
    rows = q.order_by(models.AbapAnalysisRequest.created_at.desc()).all()
    if bucket == "all":
        return rows
    return [row for row in rows if abap_analysis_menu_bucket(row) == bucket]


def _integration_base_query(db: Session, *, admin: bool, user_id: int):
    q = (
        db.query(models.IntegrationRequest)
        .options(
            joinedload(models.IntegrationRequest.owner),
            joinedload(models.IntegrationRequest.interview_messages),
            joinedload(models.IntegrationRequest.workflow_rfp).joinedload(models.RFP.messages),
        )
    )
    if admin:
        return q
    return q.filter(models.IntegrationRequest.user_id == user_id)


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
    db: Session, *, admin: bool, user_id: int
) -> tuple[dict[str, int], dict[str, list[models.IntegrationRequest]]]:
    q = _integration_base_query(db, admin=admin, user_id=user_id)
    rows = q.order_by(models.IntegrationRequest.created_at.desc()).all()
    buckets: dict[str, list[models.IntegrationRequest]] = {k: [] for k in BUCKET_ORDER}
    for row in rows:
        b = integration_menu_bucket(row)
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
) -> list[models.IntegrationRequest]:
    q = _integration_base_query(db, admin=admin, user_id=user_id)
    q = _apply_integration_filters(q, title_q=title_q, date_from=date_from, date_to=date_to)
    rows = q.order_by(models.IntegrationRequest.created_at.desc()).all()
    if bucket == "all":
        return rows
    return [row for row in rows if integration_menu_bucket(row) == bucket]


def user_proposal_pending_offer_badges(db: Session, user_id: int) -> dict[str, bool]:
    """본인 소유 요청 중 '제안' 버킷에 대해 아직 매칭되지 않은 오퍼(status=offered)가 있으면 True."""

    if not user_id:
        return {"rfp": False, "analysis": False, "integration": False}

    rfps = db.query(models.RFP).filter(models.RFP.user_id == user_id).all()
    rfp_ids = [r.id for r in rfps if rfp_landing_bucket(r) == "proposal"]

    analyses = (
        db.query(models.AbapAnalysisRequest)
        .filter(models.AbapAnalysisRequest.user_id == user_id)
        .all()
    )
    ana_ids = [r.id for r in analyses if abap_analysis_menu_bucket(r) == "proposal"]

    ints = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.user_id == user_id)
        .all()
    )
    int_ids = [r.id for r in ints if integration_menu_bucket(r) == "proposal"]

    def _has(kind: str, ids: list[int]) -> bool:
        if not ids:
            return False
        return (
            db.query(models.RequestOffer.id)
            .filter(
                models.RequestOffer.request_kind == kind,
                models.RequestOffer.request_id.in_(ids),
                models.RequestOffer.status == "offered",
            )
            .first()
            is not None
        )

    return {
        "rfp": _has("rfp", rfp_ids),
        "analysis": _has("analysis", ana_ids),
        "integration": _has("integration", int_ids),
    }
