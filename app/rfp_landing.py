"""신규 개발(SAP ABAP) 랜딩 페이지용 RFP 분류·집계."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from . import models

DEFAULT_SERVICE_ABAP_INTRO_MD_KO = """표준 RFP(개발제안요청)를 제출하면 AI 에이전트가 심층 인터뷰를 진행하고, 무료 개발 제안서를 생성합니다.
프로그램 ID·SAP 모듈·개발 유형을 중심으로 한 전형적인 ABAP 과제에 적합합니다.

- 리포트, 다이얼로그, 인터페이스, BAPI·Enhancement 등
- 첨부 파일·ABAP 코드로 맥락 공유
- 진행 상태는 홈 타일 또는 이 페이지에서 확인할 수 있습니다"""


# landing bucket keys (홈 타일과 동일 라벨)
BUCKET_ORDER = ("delivery", "proposal", "analysis", "in_progress", "draft")

VALID_URL_BUCKETS = frozenset({"all", *BUCKET_ORDER})

TILE_ORDER_WITH_ALL = ("all", "delivery", "proposal", "analysis", "in_progress", "draft")


def parse_slashed_date(value: Optional[str]) -> Optional[date]:
    """YYYYMMDD 슬래시 구분 또는 MM/DD/YYYY; 공백·빈 값은 None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.match(r"^\d{4}/\d{2}/\d{2}$", s):
        return datetime.strptime(s, "%Y/%m/%d").date()
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        parts = [int(x) for x in s.split("/")]
        if len(parts) != 3:
            return None
        month, day, year = parts[0], parts[1], parts[2]
        return date(year, month, day)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return datetime.strptime(s, "%Y-%m-%d").date()
    return None


def _rfp_base_query(db: Session, *, admin: bool, user_id: int):
    """관리자: 전체 RFP(+owner·messages); 일반: 본인만."""
    q = db.query(models.RFP).options(joinedload(models.RFP.messages))
    if admin:
        return q.options(joinedload(models.RFP.owner))
    return q.filter(models.RFP.user_id == user_id)


def _apply_title_and_created_filters(q, *, title_q: str | None, date_from: date | None, date_to: date | None):
    """제목 검색(ILike) 및 생성일(날짜 경계; DB는 naive UTC로 저장)."""
    if title_q and str(title_q).strip():
        pat = f"%{str(title_q).strip()}%"
        q = q.filter(models.RFP.title.ilike(pat))
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time())
        q = q.filter(models.RFP.created_at >= start)
    if date_to is not None:
        end_excl = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        q = q.filter(models.RFP.created_at < end_excl)
    return q


def rfp_landing_aggregate(db: Session, *, admin: bool, user_id: int) -> tuple[dict[str, int], dict[str, list[models.RFP]]]:
    """집계·버킷 분류(search 미적용 — 타일 카운터용)."""
    q = _rfp_base_query(db, admin=admin, user_id=user_id)
    rfps = q.order_by(models.RFP.created_at.desc()).all()
    buckets: dict[str, list[models.RFP]] = {k: [] for k in BUCKET_ORDER}
    for rfp in rfps:
        buckets.setdefault(rfp_landing_bucket(rfp), []).append(rfp)
    counts = {k: len(buckets[k]) for k in BUCKET_ORDER}
    return counts, buckets


def workflow_linked_rfp_bucket(rfp: models.RFP) -> str:
    """분석·연동 등에서 연결된 RFP — 신규 개발과 동일한 버킷 규칙."""
    return rfp_landing_bucket(rfp)


def rfp_landing_bucket(rfp: models.RFP) -> str:
    """
    상호 배타 단계(우선순위 위→아래).

    - delivery: FS·납품 코드 생성 완료(ready) 또는 생성 중(generating)
    - proposal: 개발 제안서 존재
    - analysis: 제안서 없음 + 인터뷰 메시지(이력) 존재
    - in_progress: 제안서 없음 + 제출됨 + 아직 인터뷰 메시지 없음
    - draft: 임시저장
    """
    fs_s = ((rfp.fs_status or "none").strip().lower() or "none")
    dc_s = ((rfp.delivered_code_status or "none").strip().lower() or "none")
    dc_ok = dc_s == "ready" and (rfp.delivered_code_text or "").strip()
    fs_ok = fs_s == "ready" and (rfp.fs_text or "").strip()
    if dc_ok or fs_ok:
        return "delivery"
    if fs_s == "generating" or dc_s == "generating":
        return "delivery"
    if (rfp.proposal_text or "").strip():
        return "proposal"
    if rfp.status == "draft":
        return "draft"
    if rfp.messages and len(rfp.messages) > 0:
        return "analysis"
    return "in_progress"


def user_rfp_landing_data(db: Session, user_id: int) -> tuple[dict[str, int], dict[str, list[models.RFP]]]:
    """
    사용자 RFP를 버킷별로 분류.

    Returns:
        counts: 각 버킷 건수
        buckets: 버킷별 RFP 목록(최신순, 객체는 이미 세션에 연결됨)
    """
    return rfp_landing_aggregate(db, admin=False, user_id=user_id)


def filtered_rfp_list_for_landing(
    db: Session,
    *,
    admin: bool,
    user_id: int,
    bucket: str,
    title_q: str | None,
    date_from: date | None,
    date_to: date | None,
) -> list[models.RFP]:
    """타일 선택 후 목록(search·날짜 반영); bucket은 'all' 또는 BUCKET_ORDER 키."""
    q = _rfp_base_query(db, admin=admin, user_id=user_id)
    q = _apply_title_and_created_filters(q, title_q=title_q, date_from=date_from, date_to=date_to)
    rfps = q.order_by(models.RFP.created_at.desc()).all()
    if bucket == "all":
        return rfps
    return [rfp for rfp in rfps if rfp_landing_bucket(rfp) == bucket]
