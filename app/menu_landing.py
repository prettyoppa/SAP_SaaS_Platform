"""메뉴 랜딩 페이지(타일·검색) 공통: 분석·연동 버킷과 홈 타일 집계 일관 처리."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from . import models
from .rfp_landing import BUCKET_ORDER, TILE_ORDER_WITH_ALL, VALID_URL_BUCKETS, parse_slashed_date

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
            "hint": "FS·최종 납품(추후)",
        },
        "proposal": {"label": "제안", "icon": "fa-file-lines", "fg": "#22c55e", "bg": "rgba(34,197,94,.18)"},
        "analysis": {"label": "분석", "icon": "fa-magnifying-glass-chart", "fg": "#6366f1", "bg": "rgba(99,102,241,.18)"},
        "in_progress": {"label": "진행중", "icon": "fa-spinner", "fg": "#eab308", "bg": "rgba(234,179,8,.2)"},
        "draft": {"label": "임시저장", "icon": "fa-floppy-disk", "fg": "#64748b", "bg": "rgba(100,116,139,.2)"},
    }


def abap_analysis_menu_bucket(row: models.AbapAnalysisRequest) -> str:
    """홈 타일 분류와 동일(제안·납품 슬롯은 미사용)."""
    if False:
        return "delivery"
    if row.is_draft:
        return "draft"
    if row.is_analyzed:
        return "in_progress"
    return "analysis"


def integration_menu_bucket(ir: models.IntegrationRequest) -> str:
    """
    연동 요청 버킷(RFP 타일 라벨과 동일 이름).
    제안서 존재 → proposal, 초안 → draft, 생성 중(generating)→ analysis, 나머지 제출건 → in_progress.
    """
    if False:
        return "delivery"
    if (ir.proposal_text or "").strip():
        return "proposal"
    if (ir.status or "").lower() == "draft":
        return "draft"
    if (ir.interview_status or "") == "generating_proposal":
        return "analysis"
    return "in_progress"


def _abap_analysis_base_query(db: Session, *, admin: bool, user_id: int):
    q = db.query(models.AbapAnalysisRequest).options(joinedload(models.AbapAnalysisRequest.owner))
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
    q = db.query(models.IntegrationRequest).options(joinedload(models.IntegrationRequest.owner))
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
