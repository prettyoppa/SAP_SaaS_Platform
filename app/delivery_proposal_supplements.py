"""요청자 제안서 .md 첨부 — 신규개발·분석개선·연동개발 공통."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import models, r2_storage
from .document_llm_digest import supplement_file_body_for_agents
from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from .proposal_section6_decisions import (
    format_decisions_for_downstream_from_raw,
    get_entity_decisions_raw,
    load_request_entity_for_decisions,
)

DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES = 15

_PROPOSAL_PRIORITY_PREAMBLE = (
    "**제안서 입력 안내:** **§6 확인 필요 사항에 대한 요청자 최종 결정**과 "
    "**요청자 제안서 파일 첨부**가 있으면 에이전트 자동 제안서보다 **우선**한다. "
    "충돌 시 §6 결정·첨부 순으로 따르고, 에이전트 제안서는 보조 참고만 한다.\n\n"
)


def list_delivery_proposal_supplements(
    db: Session, request_kind: str, request_id: int
) -> list[models.RfpProposalSupplement]:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    filters = [
        and_(
            models.RfpProposalSupplement.request_kind == kind,
            models.RfpProposalSupplement.request_id == rid,
        )
    ]
    if kind == KIND_RFP:
        filters.append(models.RfpProposalSupplement.rfp_id == rid)
    return (
        db.query(models.RfpProposalSupplement)
        .filter(or_(*filters))
        .order_by(models.RfpProposalSupplement.id.asc())
        .all()
    )


def has_delivery_proposal_supplements(db: Session, request_kind: str, request_id: int) -> bool:
    return bool(list_delivery_proposal_supplements(db, request_kind, request_id))


def merge_agent_and_requester_proposal_markdown(
    agent_proposal: str,
    supplements: list[models.RfpProposalSupplement],
    *,
    section6_decisions_block: str = "",
) -> str:
    agent_proposal = (agent_proposal or "").strip()
    s6 = (section6_decisions_block or "").strip()
    requester_parts: list[str] = []
    for sup in supplements:
        raw = r2_storage.read_bytes_from_ref(sup.stored_path)
        if raw is None:
            continue
        body, _err = supplement_file_body_for_agents(sup.filename or "proposal", raw)
        if not body:
            continue
        requester_parts.append(f"### 요청자 제안서 첨부: {sup.filename}\n\n{body.strip()}")

    owner_blocks: list[str] = []
    if s6:
        owner_blocks.append(
            "### 요청자 최종 결정 — §6 확인 필요 사항 (**최우선**)\n\n" + s6
        )
    if requester_parts:
        owner_blocks.append(
            "### 요청자 제안서 파일 첨부\n\n" + "\n\n---\n\n".join(requester_parts)
        )

    if owner_blocks:
        merged_owner = "\n\n---\n\n".join(owner_blocks)
        if agent_proposal:
            return (
                _PROPOSAL_PRIORITY_PREAMBLE
                + merged_owner
                + "\n\n---\n\n### 에이전트 생성 제안서 (참고 — 요청자 결정·첨부와 충돌 시 요청자 우선)\n\n"
                + agent_proposal
            )
        return _PROPOSAL_PRIORITY_PREAMBLE + merged_owner

    return agent_proposal


def resolved_delivery_proposal_for_downstream(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    agent_proposal_text: str | None,
) -> str:
    supplements = list_delivery_proposal_supplements(db, request_kind, request_id)
    s6_block = ""
    entity = load_request_entity_for_decisions(db, request_kind, request_id)
    if entity is not None:
        s6_block = format_decisions_for_downstream_from_raw(get_entity_decisions_raw(entity))
    return merge_agent_and_requester_proposal_markdown(
        agent_proposal_text or "",
        supplements,
        section6_decisions_block=s6_block,
    )


def proposal_ready_for_delivery(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    agent_proposal_text: str | None,
    interview_status: str | None = None,
) -> bool:
    if (agent_proposal_text or "").strip():
        return True
    if has_delivery_proposal_supplements(db, request_kind, request_id):
        return True
    return (interview_status or "").strip() == "completed"


def proposal_supplement_member_paths(request_kind: str, request_id: int) -> dict[str, str]:
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
        "proposal_supplement_upload_url": f"{base}/proposal-supplement-upload",
        "proposal_supplement_delete_url_prefix": f"{base}/proposal-supplement",
    }


def proposal_supplement_hub_template_ctx(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    return_to: str,
    can_upload: bool,
) -> dict:
    paths = proposal_supplement_member_paths(request_kind, request_id)
    return {
        "can_upload_proposal_supplement": can_upload,
        "proposal_supplements": list_delivery_proposal_supplements(db, request_kind, request_id),
        "proposal_supplement_upload_url": paths["proposal_supplement_upload_url"],
        "proposal_supplement_delete_url_prefix": paths["proposal_supplement_delete_url_prefix"],
        "proposal_supplement_return_to": return_to,
        "proposal_supplement_max_files": DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES,
    }
