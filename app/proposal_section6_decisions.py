"""제안서 §6(확인 필요 사항) — 요청자 최종 결정 인라인 입력."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP

_SECTION6_HEADING = re.compile(
    r"^##\s*6\.\s*확인\s*필요",
    re.MULTILINE | re.IGNORECASE,
)
_NEXT_H2 = re.compile(r"^##\s+\d+\.", re.MULTILINE)
_LIST_ITEM = re.compile(r"^(\s*[-*•]|\s*\d+[.)])\s+(.+)$")


def parse_section6_open_items(proposal_markdown: str) -> list[str]:
    """Development Proposal 본문에서 §6 불릿·번호 목록 항목 추출."""
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


def _empty_payload() -> dict[str, Any]:
    return {"items": [], "additional": ""}


def load_decisions_payload(raw: str | None) -> dict[str, Any]:
    if not (raw or "").strip():
        return _empty_payload()
    try:
        data = json.loads(raw)
    except Exception:
        return _empty_payload()
    if not isinstance(data, dict):
        return _empty_payload()
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    clean: list[dict[str, str]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        clean.append(
            {
                "label": str(row.get("label") or "").strip(),
                "decision": str(row.get("decision") or "").strip(),
            }
        )
    return {
        "items": clean,
        "additional": str(data.get("additional") or "").strip(),
        "updated_at": str(data.get("updated_at") or "").strip(),
    }


def save_decisions_payload(
    *,
    open_items: list[str],
    decisions_by_index: list[str],
    additional: str,
) -> str:
    items: list[dict[str, str]] = []
    for i, label in enumerate(open_items):
        dec = ""
        if i < len(decisions_by_index):
            dec = (decisions_by_index[i] or "").strip()
        items.append({"label": label, "decision": dec})
    payload = {
        "items": items,
        "additional": (additional or "").strip(),
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return json.dumps(payload, ensure_ascii=False)


def decisions_payload_for_display(
    open_items: list[str], saved: dict[str, Any]
) -> list[dict[str, str]]:
    """폼 렌더용: 제안서 §6 항목 + 저장된 결정."""
    saved_by_label = {
        (row.get("label") or "").strip(): (row.get("decision") or "").strip()
        for row in (saved.get("items") or [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, str]] = []
    for label in open_items:
        rows.append(
            {
                "label": label,
                "decision": saved_by_label.get(label, ""),
            }
        )
    if not open_items and saved.get("items"):
        for row in saved.get("items") or []:
            if isinstance(row, dict) and (row.get("label") or "").strip():
                rows.append(
                    {
                        "label": str(row.get("label") or "").strip(),
                        "decision": str(row.get("decision") or "").strip(),
                    }
                )
    return rows


def has_meaningful_decisions(saved: dict[str, Any]) -> bool:
    for row in saved.get("items") or []:
        if isinstance(row, dict) and (row.get("decision") or "").strip():
            return True
    return bool((saved.get("additional") or "").strip())


def format_decisions_for_downstream(saved: dict[str, Any]) -> str:
    if not has_meaningful_decisions(saved):
        return ""
    parts: list[str] = []
    for row in saved.get("items") or []:
        if not isinstance(row, dict):
            continue
        label = (row.get("label") or "").strip()
        dec = (row.get("decision") or "").strip()
        if not dec:
            continue
        if label:
            parts.append(f"- **확인 항목:** {label}\n  - **요청자 최종 결정:** {dec}")
        else:
            parts.append(f"- {dec}")
    add = (saved.get("additional") or "").strip()
    if add:
        parts.append(f"\n**추가 최종 결정·메모:**\n{add}")
    if not parts:
        return ""
    return "\n".join(parts).strip()


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


def member_paths_for_decisions(request_kind: str, request_id: int) -> dict[str, str]:
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
    return {"proposal_section6_decisions_save_url": f"{base}/proposal-section6-decisions"}


def section6_decisions_flash_from_query(request) -> dict[str, str] | None:
    if not request:
        return None
    qp = getattr(request, "query_params", None) or {}
    if (qp.get("section6_decisions") or "").strip() == "ok":
        return {
            "kind": "success",
            "ko": "§6 확인 필요 사항에 대한 최종 결정을 저장했습니다.",
            "en": "Your section 6 decisions have been saved.",
        }
    err = (qp.get("section6_decisions_err") or "").strip()
    if err == "forbidden":
        return {
            "kind": "danger",
            "ko": "요청 소유자만 저장할 수 있습니다.",
            "en": "Only the request owner can save decisions.",
        }
    if err:
        return {
            "kind": "warning",
            "ko": "저장하지 못했습니다. 다시 시도해 주세요.",
            "en": "Could not save. Please try again.",
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
) -> dict[str, Any]:
    open_items = parse_section6_open_items(agent_proposal_text or "")
    saved = load_decisions_payload(decisions_raw)
    rows = decisions_payload_for_display(open_items, saved)
    paths = member_paths_for_decisions(request_kind, request_id)
    show_panel = bool(
        can_edit or has_meaningful_decisions(saved) or open_items
    )
    return {
        "proposal_section6_show_panel": show_panel,
        "can_edit_proposal_section6_decisions": can_edit,
        "proposal_section6_open_items": open_items,
        "proposal_section6_decision_rows": rows,
        "proposal_section6_additional": saved.get("additional") or "",
        "proposal_section6_has_saved": has_meaningful_decisions(saved),
        "proposal_section6_decisions_save_url": paths["proposal_section6_decisions_save_url"],
        "proposal_section6_return_to": return_to,
    }
