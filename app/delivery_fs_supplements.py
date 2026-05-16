"""컨설턴트 FS .md 첨부 — 신규개발·분석개선·연동개발 공통."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import models, r2_storage

KIND_RFP = "rfp"
KIND_ANALYSIS = "analysis"
KIND_INTEGRATION = "integration"

# 컨설턴트 FS .md: 요청당 누적 상한 · 1회 스테이징(드롭존) 상한
DELIVERY_FS_SUPPLEMENT_MAX_FILES = 15

_FS_PRIORITY_PREAMBLE = (
    "**코드 생성 FS 입력 안내:** 아래에 **컨설턴트 FS 첨부**가 있으면 "
    "에이전트 자동 FS와 충돌할 때 **첨부 FS를 최우선**으로 구현한다. "
    "첨부가 없으면 에이전트 FS만 사용한다.\n\n"
)


def list_delivery_fs_supplements(
    db: Session, request_kind: str, request_id: int
) -> list[models.RfpFsSupplement]:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    filters = [
        and_(
            models.RfpFsSupplement.request_kind == kind,
            models.RfpFsSupplement.request_id == rid,
        )
    ]
    if kind == KIND_RFP:
        filters.append(models.RfpFsSupplement.rfp_id == rid)
    return (
        db.query(models.RfpFsSupplement)
        .filter(or_(*filters))
        .order_by(models.RfpFsSupplement.id.asc())
        .all()
    )


def merge_agent_and_consultant_fs_markdown(
    agent_fs: str,
    supplements: list[models.RfpFsSupplement],
) -> tuple[str | None, str | None]:
    """
    ABAP/연동 코드 생성용 FS 본문.
    첨부가 있으면 **첨부를 앞에** 두고 에이전트 FS는 참고로 둔다.
    첨부만 있어도 생성 가능.
    """
    agent_fs = (agent_fs or "").strip()
    consultant_parts: list[str] = []
    for sup in supplements:
        raw = r2_storage.read_bytes_from_ref(sup.stored_path)
        if raw is None:
            return None, f"FS 첨부를 읽을 수 없습니다: {sup.filename}"
        try:
            body = raw.decode("utf-8")
        except Exception:
            body = raw.decode("utf-8", errors="replace")
        consultant_parts.append(f"### 컨설턴트 FS 첨부: {sup.filename}\n\n{body.strip()}")

    if consultant_parts:
        merged_consult = "\n\n---\n\n".join(consultant_parts)
        if agent_fs:
            combined = (
                _FS_PRIORITY_PREAMBLE
                + "### 컨설턴트 FS 첨부 (코드 생성 시 **최우선**)\n\n"
                + merged_consult
                + "\n\n---\n\n### 에이전트 생성 FS (참고 — 첨부와 충돌 시 첨부 우선)\n\n"
                + agent_fs
            )
            return combined, None
        return _FS_PRIORITY_PREAMBLE + merged_consult, None

    if not agent_fs:
        return (
            None,
            "FS 본문이 없습니다. FS 에이전트 생성을 완료하거나 컨설턴트 FS .md를 첨부하세요.",
        )
    return agent_fs, None


def resolved_delivery_fs_for_codegen(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    agent_fs_text: str | None,
) -> tuple[str | None, str | None]:
    supplements = list_delivery_fs_supplements(db, request_kind, request_id)
    return merge_agent_and_consultant_fs_markdown(agent_fs_text or "", supplements)


def fs_supplement_hub_template_ctx(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    return_to: str,
) -> dict:
    paths = fs_supplement_admin_paths(request_kind, request_id)
    return {
        "fs_supplements": list_delivery_fs_supplements(db, request_kind, request_id),
        "fs_supplement_upload_url": paths["fs_supplement_upload_url"],
        "fs_supplement_delete_url_prefix": paths["fs_supplement_delete_url_prefix"],
        "fs_supplement_return_to": return_to,
        "fs_supplement_max_files": DELIVERY_FS_SUPPLEMENT_MAX_FILES,
    }


def fs_supplement_admin_paths(request_kind: str, request_id: int) -> dict[str, str]:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == KIND_RFP:
        base = f"/admin/rfp/{rid}/delivery"
    elif kind == KIND_ANALYSIS:
        base = f"/admin/abap-analysis/{rid}/delivery"
    elif kind == KIND_INTEGRATION:
        base = f"/admin/integration/{rid}/delivery"
    else:
        raise ValueError(f"unknown request_kind: {request_kind}")
    return {
        "fs_supplement_upload_url": f"{base}/fs-supplement-upload",
        "fs_supplement_delete_url_prefix": f"{base}/fs-supplement",
    }
