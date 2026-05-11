"""운영 플레이북 — Admin에 누적한 규칙을 에이전트 프롬프트에 주입."""

from __future__ import annotations

import json
from dataclasses import dataclass
from sqlalchemy.orm import Session

from . import models

# Admin 폼·코드에서 공통으로 쓰는 stage 문자열
STAGE_INTERVIEW = "interview"
STAGE_PROPOSAL = "proposal"
STAGE_FS_ABAP = "fs_abap"
STAGE_DELIVERED_ABAP = "delivered_abap"
STAGE_ANALYSIS = "analysis"
STAGE_INTEGRATION_FS = "integration_fs"
STAGE_INTEGRATION_DELIVERABLE = "integration_deliverable"

ALL_STAGE_CHOICES: tuple[tuple[str, str], ...] = (
    (STAGE_INTERVIEW, "인터뷰(질문 생성·라운드 진행)"),
    (STAGE_PROPOSAL, "Development Proposal"),
    (STAGE_FS_ABAP, "유료 FS (ABAP·RFP)"),
    (STAGE_DELIVERED_ABAP, "납품 ABAP (RFP)"),
    (STAGE_ANALYSIS, "분석 요청 전용 LLM (초기 미주입 가능)"),
    (STAGE_INTEGRATION_FS, "연동 FS"),
    (STAGE_INTEGRATION_DELIVERABLE, "연동 구현 가이드/납품"),
)

MAX_PLAYBOOK_CHARS = 12_000


@dataclass(frozen=True)
class PlaybookContext:
    """플레이북 매칭 컨텍스트."""

    entity: str  # rfp | integration | abap_analysis
    stage: str
    workflow_origin: str | None = None  # RFP: direct | abap_analysis | integration ; 연동 dict: integration_native


def _parse_stages(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    try:
        j = json.loads(raw)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass
    return []


def _row_matches(ctx: PlaybookContext, row: models.AgentPlaybookEntry) -> bool:
    ent = (row.match_entity or "any").strip().lower()
    if ent != "any" and ent != (ctx.entity or "").strip().lower():
        return False

    wo_row = (row.match_workflow_origin or "any").strip().lower()
    wo_ctx = (ctx.workflow_origin or "").strip().lower() if ctx.workflow_origin else ""
    if ctx.entity == "rfp":
        if wo_row != "any" and wo_row != wo_ctx:
            return False
    elif ctx.entity == "integration":
        # 연동 네이티브는 dict 상 integration_native; 향후 확장 대비 exact 매칭
        if wo_row != "any" and wo_row != wo_ctx:
            return False
    else:
        # abap_analysis: workflow_origin 필터는 보통 any만 쓰거나 동일 출처 확장 시 사용
        if wo_row != "any" and wo_ctx and wo_row != wo_ctx:
            return False

    stages = _parse_stages(row.match_stages_json)
    if not stages:
        return False
    st = (ctx.stage or "").strip().lower()
    return st in {s.strip().lower() for s in stages}


def build_playbook_addon(db: Session, ctx: PlaybookContext) -> str:
    """매칭되는 활성 플레이북 본문을 이어붙인 문자열(없으면 빈 문자열)."""
    rows = (
        db.query(models.AgentPlaybookEntry)
        .filter(models.AgentPlaybookEntry.active.is_(True))
        .order_by(models.AgentPlaybookEntry.priority.desc(), models.AgentPlaybookEntry.id.desc())
        .all()
    )
    parts: list[str] = []
    n = 0
    for row in rows:
        if not _row_matches(ctx, row):
            continue
        title = (row.title or "").strip() or f"#{row.id}"
        body = (row.body or "").strip()
        if not body:
            continue
        parts.append(f"### {title}\n{body}")
        n += 1
    if not parts:
        return ""
    blob = "\n\n---\n\n".join(parts)
    if len(blob) > MAX_PLAYBOOK_CHARS:
        blob = blob[: MAX_PLAYBOOK_CHARS - 40] + "\n\n…(플레이북 길이 상한으로 잘림)…"
    return blob


def playbook_prompt_wrap(addon: str) -> str:
    """에이전트 Task description 끝에 붙이는 고정 래퍼."""
    t = (addon or "").strip()
    if not t:
        return ""
    return (
        "\n\n[운영 플레이북 — 반드시 준수]\n"
        + t
        + "\n[운영 플레이북 끝]\n"
    )


def stages_json_from_list(stages: list[str]) -> str:
    clean = [str(s).strip() for s in stages if str(s).strip()]
    return json.dumps(clean, ensure_ascii=False)
