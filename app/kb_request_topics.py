"""회원 요청 데이터 → 익명 통계 기반 KB 주제 제안(자동 공개 금지)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from . import models
from .kb_slug import ensure_unique_kb_slug, slugify_kb_title

RequestMenuKind = Literal["abap", "analysis", "integration"]


@dataclass(frozen=True)
class KbTopicSuggestion:
    menu_kind: RequestMenuKind
    menu_label: str
    topic_label: str
    request_count: int
    suggested_title: str
    suggested_slug: str
    suggested_category: str
    suggested_excerpt: str
    suggested_meta_description: str
    suggested_body_md: str
    source_note: str


def _split_csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _menu_meta(kind: RequestMenuKind) -> tuple[str, str]:
    if kind == "abap":
        return "신규 개발", "abap"
    if kind == "analysis":
        return "분석·개선", "analysis"
    return "연동 개발", "integration"


def _outline_body(menu_label: str, topic_label: str, count: int) -> str:
    return "\n".join(
        [
            f"## 개요",
            "",
            f"Catch Lab **{menu_label}** 메뉴에서 수집된 익명 통계 기준, "
            f"**{topic_label}** 관련 요청이 **{count}건** 이상 확인되었습니다. "
            "아래는 회사명·개인정보·요청 본문 없이 집계한 패턴입니다.",
            "",
            f"## {topic_label}에서 자주 보이는 요청 유형",
            "",
            "- (관리자: AI에게 「실무 체크리스트 5개」를 요청해 이 섹션을 채우세요.)",
            "- ",
            "",
            "## 설계·구현 시 체크포인트",
            "",
            "- ",
            "",
            "## Catch Lab으로 이어지기",
            "",
            "막연한 요구사항은 **AI 개발 제안서(무료)** 로 구조화한 뒤, "
            "필요 시 전문 컨설턴트와 납품까지 이어갈 수 있습니다.",
            "",
        ]
    )


def collect_kb_topic_suggestions(db: Session, *, limit: int = 12) -> list[KbTopicSuggestion]:
    """제출된 요청의 모듈·유형만 집계 — 제목·본문·회원 정보는 사용하지 않음."""
    buckets: Counter[tuple[RequestMenuKind, str]] = Counter()

    rfps = (
        db.query(models.RFP)
        .filter(models.RFP.status != "draft")
        .all()
    )
    for r in rfps:
        origin = (r.workflow_origin or "direct").strip().lower()
        if origin == "abap_analysis":
            kind: RequestMenuKind = "analysis"
        elif origin == "integration":
            kind = "integration"
        else:
            kind = "abap"
        mods = _split_csv(r.sap_modules)
        if not mods:
            buckets[(kind, "일반")] += 1
            continue
        for mod in mods[:3]:
            buckets[(kind, mod.upper())] += 1

    analyses = (
        db.query(models.AbapAnalysisRequest)
        .filter(models.AbapAnalysisRequest.is_draft == False)
        .all()
    )
    for row in analyses:
        buckets[("analysis", "ABAP 분석")] += 1

    integrations = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.status != "draft")
        .all()
    )
    for row in integrations:
        types = _split_csv(row.impl_types)
        label = types[0] if types else "연동"
        buckets[("integration", label)] += 1

    out: list[KbTopicSuggestion] = []
    for (menu_kind, topic_label), count in buckets.most_common(limit * 2):
        if count < 2:
            continue
        menu_label, category = _menu_meta(menu_kind)
        title = f"SAP {topic_label} — {menu_label} 요청에서 자주 보는 패턴"
        base_slug = slugify_kb_title(f"{category}-{topic_label}-patterns")
        slug = ensure_unique_kb_slug(db, base_slug)
        excerpt = (
            f"{menu_label} 요청 중 {topic_label} 관련 익명 집계 {count}건. "
            "실무 체크리스트와 설계 시 유의점을 정리합니다."
        )
        meta = excerpt[:155]
        body = _outline_body(menu_label, topic_label, count)
        out.append(
            KbTopicSuggestion(
                menu_kind=menu_kind,
                menu_label=menu_label,
                topic_label=topic_label,
                request_count=count,
                suggested_title=title,
                suggested_slug=slug,
                suggested_category=category,
                suggested_excerpt=excerpt,
                suggested_meta_description=meta,
                suggested_body_md=body,
                source_note=f"{menu_label} 익명 집계 {count}건 (모듈/유형만, 원문 미포함)",
            )
        )
        if len(out) >= limit:
            break
    return out
