"""제안서 §6(확인 필요 사항) — 요청자 추가 인터뷰·최종 결정."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from .proposal_section6_interview import (
    format_section6_for_downstream,
    has_section6_decisions,
    load_section6_payload,
    save_section6_payload,
)

_SECTION6_HEADING = re.compile(
    r"^##\s*6\.\s*확인\s*필요",
    re.MULTILINE | re.IGNORECASE,
)
_NEXT_H2 = re.compile(r"^##\s+\d+\.", re.MULTILINE)
_LIST_ITEM = re.compile(r"^(\s*[-*•]|\s*\d+[.)])\s+(.+)$")


def parse_section6_open_items(proposal_markdown: str) -> list[str]:
    text = (proposal_markdown or "").strip()
    if not text:
        return []
    m = _SECTION6_HEADING.search(text)
    if not m:
        return []
    rest = text[m.end() :]
    end_m = _NEXT_H2.search(rest)
    block = rest[: end_m.start()] if end_m else rest
    items: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        lm = _LIST_ITEM.match(line)
        if lm:
            label = (lm.group(2) or "").strip()
            if label:
                items.append(label)
        elif items and not line.startswith("#"):
            items[-1] = (items[-1] + " " + line).strip()
    return items


def load_request_entity_for_decisions(
    db: Session, request_kind: str, request_id: int
) -> models.RFP | models.IntegrationRequest | models.AbapAnalysisRequest | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == KIND_RFP:
        return db.query(models.RFP).filter(models.RFP.id == rid).first()
    if kind == KIND_INTEGRATION:
        return (
            db.query(models.IntegrationRequest)
            .filter(models.IntegrationRequest.id == rid)
            .first()
        )
    if kind == KIND_ANALYSIS:
        return (
            db.query(models.AbapAnalysisRequest)
            .filter(models.AbapAnalysisRequest.id == rid)
            .first()
        )
    return None


def get_entity_decisions_raw(entity: Any) -> str | None:
    return getattr(entity, "proposal_section6_decisions_json", None)


def set_entity_decisions_raw(entity: Any, payload_json: str) -> None:
    entity.proposal_section6_decisions_json = payload_json


def member_paths_for_section6(request_kind: str, request_id: int) -> dict[str, str]:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == KIND_RFP:
        base = f"/rfp/{rid}"
    elif kind == KIND_ANALYSIS:
        base = f"/abap-analysis/{rid}"
    elif kind == KIND_INTEGRATION:
        base = f"/integration/{rid}"
    else:
        raise ValueError(f"unknown request_kind: {request_kind}")
    return {
        "proposal_section6_interview_start_url": f"{base}/proposal-section6-interview/start",
        "proposal_section6_interview_answer_url": f"{base}/proposal-section6-interview/answer",
    }


def section6_decisions_flash_from_query(request) -> dict[str, str] | None:
    if not request:
        return None
    qp = getattr(request, "query_params", None) or {}
    if (qp.get("section6_decisions") or "").strip() == "ok":
        return {
            "kind": "success",
            "ko": "6. 확인 필요 사항에 대한 최종 결정을 저장했습니다.",
            "en": "Your section 6 decisions have been saved.",
        }
    if (qp.get("section6_interview") or "").strip() == "started":
        return {
            "kind": "info",
            "ko": "추가 인터뷰를 시작했습니다. 질문에 답해 주세요.",
            "en": "Follow-up interview started. Please answer the questions.",
        }
    err = (qp.get("section6_decisions_err") or "").strip()
    if err == "answer_invalid":
        return {
            "kind": "warning",
            "ko": "좋아요·싫어요로 선택하거나 보충란에 2자 이상 입력해 주세요.",
            "en": "Select thumbs up/down or enter at least 2 characters in the notes field.",
        }
    if err == "forbidden":
        return {
            "kind": "danger",
            "ko": "요청 소유자만 진행할 수 있습니다.",
            "en": "Only the request owner can continue.",
        }
    if err:
        return {
            "kind": "warning",
            "ko": "처리하지 못했습니다. 다시 시도해 주세요.",
            "en": "Could not complete. Please try again.",
        }
    return None


def proposal_section6_hub_template_ctx(
    *,
    request_kind: str,
    request_id: int,
    agent_proposal_text: str | None,
    decisions_raw: str | None,
    can_edit: bool,
    return_to: str,
    request_title: str = "",
) -> dict[str, Any]:
    open_items = parse_section6_open_items(agent_proposal_text or "")
    payload = load_section6_payload(decisions_raw)
    inv = payload.get("interview") or {}
    if open_items and not (inv.get("open_items") or []):
        inv["open_items"] = open_items
        payload["interview"] = inv

    stored_open = list(inv.get("open_items") or open_items)
    turns = inv.get("turns") or []
    status = (inv.get("status") or "idle").strip()
    current_index = int(inv.get("current_index") or 0)
    current_turn = None
    if status == "active" and turns and current_index < len(turns):
        current_turn = turns[current_index]

    paths = member_paths_for_section6(request_kind, request_id)
    show_panel = bool(can_edit or has_section6_decisions(payload) or stored_open)

    completed_turns = [
        t
        for t in turns
        if isinstance(t, dict) and (t.get("decision_text") or "").strip()
    ]

    return {
        "proposal_section6_show_panel": show_panel,
        "can_edit_proposal_section6_decisions": can_edit,
        "proposal_section6_open_items": stored_open,
        "proposal_section6_interview_status": status,
        "proposal_section6_interview_total": len(stored_open),
        "proposal_section6_interview_index": current_index + 1 if current_turn else 0,
        "proposal_section6_current_turn": current_turn,
        "proposal_section6_completed_turns": completed_turns,
        "proposal_section6_interview_complete": status == "complete",
        "proposal_section6_has_saved": has_section6_decisions(payload),
        "proposal_section6_interview_start_url": paths["proposal_section6_interview_start_url"],
        "proposal_section6_interview_answer_url": paths["proposal_section6_interview_answer_url"],
        "proposal_section6_return_to": return_to,
        "proposal_section6_request_title": request_title,
    }


def format_decisions_for_downstream_from_raw(raw: str | None) -> str:
    return format_section6_for_downstream(load_section6_payload(raw))
