"""DevType 조회 — usage(abap|integration|both)로 신규·연동 화면을 분리합니다."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models

# 연동 구현 형태 코드가 DB에서 삭제된 경우(레거시) 표시용
INTEGRATION_IMPL_FALLBACK_LABELS: dict[str, str] = {
    "excel_vba": "Excel / VBA 매크로",
    "python_script": "Python 스크립트",
    "small_webapp": "소규모 웹앱",
    "windows_batch": "Windows 배치 / 작업 스케줄러",
    "api_integration": "API·시스템 연동",
    "other": "기타",
}


def active_abap_devtypes(db: Session) -> list[models.DevType]:
    """신규 RFP·코드 갤러리·ABAP 분석 폼의 개발 유형."""
    return (
        db.query(models.DevType)
        .filter(
            models.DevType.is_active == True,
            or_(
                models.DevType.usage == "abap",
                models.DevType.usage == "both",
                models.DevType.usage.is_(None),
            ),
        )
        .order_by(models.DevType.sort_order, models.DevType.id)
        .all()
    )


def active_integration_impl_devtypes(db: Session) -> list[models.DevType]:
    """연동 개발 요청 — 구현 형태(구 impl_types) 칩."""
    return (
        db.query(models.DevType)
        .filter(
            models.DevType.is_active == True,
            or_(
                models.DevType.usage == "integration",
                models.DevType.usage == "both",
            ),
        )
        .order_by(models.DevType.sort_order, models.DevType.id)
        .all()
    )


def integration_impl_allowed_codes(db: Session) -> set[str]:
    return {r.code for r in active_integration_impl_devtypes(db)}


def integration_impl_labels_map(db: Session) -> dict[str, str]:
    """배지·목록용: 코드 → 한글 라벨 (비활성·삭제 코드는 fallback)."""
    m = dict(INTEGRATION_IMPL_FALLBACK_LABELS)
    for r in (
        db.query(models.DevType)
        .filter(or_(models.DevType.usage == "integration", models.DevType.usage == "both"))
        .all()
    ):
        m[r.code] = r.label_ko
    return m


def format_integration_impl_types_for_llm(db: Session, impl_csv: str) -> str:
    """인터뷰·후속 질문·워크플로 시드용: 관리 라벨 + 코드."""
    codes = [x.strip() for x in (impl_csv or "").split(",") if x.strip()]
    if not codes:
        return "—"
    parts: list[str] = []
    for c in codes:
        row = db.query(models.DevType).filter(models.DevType.code == c).first()
        if row:
            parts.append(f"{row.label_ko} ({c})")
        else:
            parts.append(f"{INTEGRATION_IMPL_FALLBACK_LABELS.get(c, c)} ({c})")
    return ", ".join(parts)
