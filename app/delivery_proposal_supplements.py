"""요청자 제안서 .md 첨부 — 신규개발·분석개선·연동개발 공통."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import models, r2_storage
from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP

DELIVERY_PROPOSAL_SUPPLEMENT_MAX_FILES = 15

_PROPOSAL_PRIORITY_PREAMBLE = (
    "**제안서 입력 안내:** 아래에 **요청자 제안서 첨부**가 있으면 "
    "에이전트 자동 제안서와 충돌할 때 **첨부 제안서를 최우선**으로 따른다. "
    "첨부가 없으면 에이전트 제안서만 사용한다.\n\n"
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
) -> str:
    agent_proposal = (agent_proposal or "").strip()
    requester_parts: list[str] = []
    for sup in supplements:
        raw = r2_storage.read_bytes_from_ref(sup.stored_path)
        if raw is None:
            continue
        try:
            body = raw.decode("utf-8")
        except Exception:
            body = raw.decode("utf-8", errors="replace")
        requester_parts.append(f"### 요청자 제안서 첨부: {sup.filename}\n\n{body.strip()}")

    if requester_parts:
        merged_req = "\n\n---\n\n".join(requester_parts)
        if agent_proposal:
            return (
                _PROPOSAL_PRIORITY_PREAMBLE
                + "### 요청자 제안서 첨부 (**최우선**)\n\n"
                + merged_req
                + "\n\n---\n\n### 에이전트 생성 제안서 (참고 — 첨부와 충돌 시 첨부 우선)\n\n"
                + agent_proposal
            )
        return _PROPOSAL_PRIORITY_PREAMBLE + merged_req

    return agent_proposal


def resolved_delivery_proposal_for_downstream(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    agent_proposal_text: str | None,
) -> str:
    supplements = list_delivery_proposal_supplements(db, request_kind, request_id)
    return merge_agent_and_requester_proposal_markdown(agent_proposal_text or "", supplements)


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
