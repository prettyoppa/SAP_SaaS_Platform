"""RFP 통합 허브 — 분석·개선(abap_analysis)에서 연결된 건의 단계별 미러 표시용 컨텍스트."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session, joinedload

from . import models
from .rfp_reference_code import reference_code_program_groups_for_tabs


def abap_row_attachment_entries(row: models.AbapAnalysisRequest) -> list[dict]:
    if not getattr(row, "attachments_json", None):
        return []
    try:
        data = json.loads(row.attachments_json)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("path")]
    except Exception:
        pass
    return []


def pair_abap_followup_turns(msgs: list) -> list[dict[str, Any]]:
    """user → assistant 순을 한 턴으로 묶어 읽기 전용 로그에 사용."""
    out: list[dict[str, Any]] = []
    i = 0
    n = len(msgs)
    while i < n:
        m = msgs[i]
        role = (getattr(m, "role", None) or "").strip().lower()
        if role == "user":
            q = m
            a = None
            if i + 1 < n and (getattr(msgs[i + 1], "role", None) or "").strip().lower() == "assistant":
                a = msgs[i + 1]
                i += 2
            else:
                i += 1
            out.append({"question": q, "answer": a})
        elif role == "assistant":
            out.append({"question": None, "answer": m})
            i += 1
        else:
            i += 1
    return out


def load_workflow_abap_mirror_context(db: Session, user: models.User, rfp: models.RFP) -> dict[str, Any] | None:
    """workflow_origin=abap_analysis 이고 연결된 AbapAnalysisRequest 가 있을 때만."""
    wo = (getattr(rfp, "workflow_origin", None) or "").strip()
    if wo != "abap_analysis":
        return None
    q = (
        db.query(models.AbapAnalysisRequest)
        .options(joinedload(models.AbapAnalysisRequest.followup_messages))
        .filter(models.AbapAnalysisRequest.workflow_rfp_id == rfp.id)
    )
    if not getattr(user, "is_admin", False):
        # RFP 소유자와 분석 요청 소유자는 동일 워크플로에서 일치해야 함
        q = q.filter(models.AbapAnalysisRequest.user_id == user.id)
    row = q.first()
    if not row:
        return None
    analysis: dict = {}
    if row.analysis_json:
        try:
            j = json.loads(row.analysis_json)
            if isinstance(j, dict):
                analysis = j
        except Exception:
            analysis = {}
    msgs = sorted(
        list(row.followup_messages or []),
        key=lambda m: (m.created_at or m.id or 0),
    )
    followup_turns = pair_abap_followup_turns(msgs)
    att = abap_row_attachment_entries(row)
    groups = reference_code_program_groups_for_tabs(row.reference_code_payload)
    return {
        "wf_abap_mirror": True,
        "wf_row": row,
        "wf_analysis": analysis,
        "wf_attachment_entries": att,
        "wf_source_program_groups": groups,
        "wf_followup_turns": followup_turns,
        "wf_tabs_base_id": f"wf-abap-mirror-{row.id}-{rfp.id}",
    }
