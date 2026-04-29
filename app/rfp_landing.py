"""신규 개발(SAP ABAP) 랜딩 페이지용 RFP 분류·집계."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from . import models

DEFAULT_SERVICE_ABAP_INTRO_MD_KO = """표준 RFP(개발제안요청)를 제출하면 AI 에이전트가 심층 인터뷰를 진행하고, 무료 개발 제안서를 생성합니다.
프로그램 ID·SAP 모듈·개발 유형을 중심으로 한 전형적인 ABAP 과제에 적합합니다.

- 리포트, 다이얼로그, 인터페이스, BAPI·Enhancement 등
- 첨부 파일·ABAP 코드로 맥락 공유
- 진행 상태는 홈 타일 또는 이 페이지에서 확인할 수 있습니다"""


# landing bucket keys (홈 타일과 동일 라벨)
BUCKET_ORDER = ("delivery", "proposal", "analysis", "in_progress", "draft")


def rfp_landing_bucket(rfp: models.RFP) -> str:
    """
    상호 배타 단계(우선순위 위→아래).

    - delivery: FS 납품 완료 (미구현 → 항상 제외)
    - proposal: 개발 제안서 존재
    - analysis: 제안서 없음 + 인터뷰 메시지(이력) 존재
    - in_progress: 제안서 없음 + 제출됨 + 아직 인터뷰 메시지 없음
    - draft: 임시저장
    """
    # FS/납품 구간 — 추후 필드 추가 시 여기서 반환
    if False:
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
    rfps = (
        db.query(models.RFP)
        .options(joinedload(models.RFP.messages))
        .filter(models.RFP.user_id == user_id)
        .order_by(models.RFP.created_at.desc())
        .all()
    )
    buckets: dict[str, list[models.RFP]] = {k: [] for k in BUCKET_ORDER}
    for rfp in rfps:
        b = rfp_landing_bucket(rfp)
        buckets.setdefault(b, []).append(rfp)

    counts = {k: len(buckets[k]) for k in BUCKET_ORDER}
    return counts, buckets
