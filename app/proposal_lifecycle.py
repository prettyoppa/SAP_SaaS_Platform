"""개발 제안서(에이전트 본문) 삭제·인터뷰 재시작 가드."""

from __future__ import annotations

from typing import Any, Protocol


class _ProposalEntity(Protocol):
    proposal_text: str | None
    interview_status: str | None
    fs_status: str | None
    delivered_code_status: str | None


def has_agent_proposal_text(entity: _ProposalEntity) -> bool:
    return bool((getattr(entity, "proposal_text", None) or "").strip())


def delivery_pipeline_started(entity: _ProposalEntity) -> bool:
    fs_s = (getattr(entity, "fs_status", None) or "none").strip()
    dc_s = (getattr(entity, "delivered_code_status", None) or "none").strip()
    return fs_s != "none" or dc_s != "none"


def proposal_is_generating(entity: _ProposalEntity) -> bool:
    return (getattr(entity, "interview_status", None) or "").strip() == "generating_proposal"


def proposal_delete_block_reason(entity: _ProposalEntity) -> str | None:
    """None이면 삭제 가능. 그 외 stable code."""
    if proposal_is_generating(entity):
        return "generating"
    if delivery_pipeline_started(entity):
        return "downstream_started"
    if not has_agent_proposal_text(entity):
        return "no_proposal"
    return None


def interview_reset_block_reason(entity: _ProposalEntity) -> str | None:
    if proposal_is_generating(entity):
        return "generating"
    if has_agent_proposal_text(entity):
        return "proposal_exists"
    return None


def clear_agent_proposal(entity: Any) -> None:
    entity.proposal_text = None
    if proposal_is_generating(entity):
        entity.interview_status = "completed"
    elif (getattr(entity, "interview_status", None) or "").strip() not in (
        "in_progress",
        "pending",
    ):
        entity.interview_status = "completed"
