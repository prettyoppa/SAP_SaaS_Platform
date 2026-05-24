"""컨설턴트 FS .md 첨부 — 신규개발·분석개선·연동개발 공통."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import models, r2_storage
from .document_llm_digest import supplement_file_body_for_agents

KIND_RFP = "rfp"
KIND_ANALYSIS = "analysis"
KIND_INTEGRATION = "integration"

# 컨설턴트 FS .md: 요청당 누적 상한 · 1회 스테이징(드롭존) 상한
DELIVERY_FS_SUPPLEMENT_MAX_FILES = 15
FS_CONSULTANT_ADDENDUM_MAX_CHARS = 80_000

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


def load_fs_consultant_addendum(db: Session, request_kind: str, request_id: int) -> str:
    from .request_offer_lifecycle import load_request_row

    row = load_request_row(db, request_kind, request_id)
    if row is None:
        return ""
    return (getattr(row, "fs_consultant_addendum", None) or "").strip()


def _consultant_addendum_block(addendum: str) -> str | None:
    text = (addendum or "").strip()
    if not text:
        return None
    return f"### 컨설턴트 FS 추가 보완 (텍스트)\n\n{text}"


def merge_agent_and_consultant_fs_markdown(
    agent_fs: str,
    supplements: list[models.RfpFsSupplement],
    consultant_addendum: str | None = None,
) -> tuple[str | None, str | None]:
    """
    ABAP/연동 코드 생성용 FS 본문.
    첨부가 있으면 **첨부를 앞에** 두고 에이전트 FS는 참고로 둔다.
    첨부만 있어도 생성 가능.
    """
    agent_fs = (agent_fs or "").strip()
    consultant_parts: list[str] = []
    addendum_block = _consultant_addendum_block(consultant_addendum or "")
    if addendum_block:
        consultant_parts.append(addendum_block)
    for sup in supplements:
        raw = r2_storage.read_bytes_from_ref(sup.stored_path)
        if raw is None:
            return None, f"FS 첨부를 읽을 수 없습니다: {sup.filename}"
        body, err = supplement_file_body_for_agents(sup.filename or "fs", raw)
        if err or not body:
            return None, err or f"FS 첨부를 해석하지 못했습니다: {sup.filename}"
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
    consultant_addendum: str | None = None,
) -> tuple[str | None, str | None]:
    supplements = list_delivery_fs_supplements(db, request_kind, request_id)
    if consultant_addendum is None:
        consultant_addendum = load_fs_consultant_addendum(db, request_kind, request_id)
    return merge_agent_and_consultant_fs_markdown(
        agent_fs_text or "", supplements, consultant_addendum=consultant_addendum
    )


def resolved_delivery_fs_for_member_view(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    agent_fs_text: str | None,
) -> str:
    """허브 미리보기·다운로드용 — 병합 실패 시 에이전트 FS만."""
    body, _err = resolved_delivery_fs_for_codegen(
        db,
        request_kind=request_kind,
        request_id=request_id,
        agent_fs_text=agent_fs_text,
    )
    if body and body.strip():
        return body.strip()
    return (agent_fs_text or "").strip()


def fs_supplement_hub_template_ctx(
    db: Session,
    *,
    request_kind: str,
    request_id: int,
    return_to: str,
) -> dict:
    from .request_offer_lifecycle import load_request_row

    paths = fs_supplement_admin_paths(request_kind, request_id)
    readonly = "console-readonly" in (return_to or "")
    addendum = load_fs_consultant_addendum(db, request_kind, request_id)
    row = load_request_row(db, request_kind, request_id)
    fs_stat = (getattr(row, "fs_status", None) or "none").strip() if row else "none"
    return {
        "fs_supplements": list_delivery_fs_supplements(db, request_kind, request_id),
        "fs_supplement_upload_url": paths["fs_supplement_upload_url"],
        "fs_supplement_delete_url_prefix": paths["fs_supplement_delete_url_prefix"],
        "fs_consultant_addendum": addendum,
        "fs_addendum_save_url": paths["fs_addendum_save_url"],
        "fs_clear_deliverable_url": paths["fs_clear_deliverable_url"],
        "delivered_code_clear_url": paths["delivered_code_clear_url"],
        "fs_supplement_return_to": return_to,
        "fs_stat_for_delivery": fs_stat,
        "delivery_return_to_devcode": hub_delivery_return_path(
            request_kind, request_id, phase="devcode", readonly_console=readonly
        ),
        "fs_supplement_max_files": DELIVERY_FS_SUPPLEMENT_MAX_FILES,
        "fs_addendum_max_chars": FS_CONSULTANT_ADDENDUM_MAX_CHARS,
    }


def hub_delivery_return_path(
    request_kind: str,
    request_id: int,
    *,
    phase: str = "fs",
    readonly_console: bool = False,
) -> str:
    """통합 허브 FS·개발코드 단계 URL (별도 /admin/.../delivery 콘솔 대신)."""
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    ph = (phase or "fs").strip().lower()
    if kind == KIND_RFP:
        base = f"/rfp/{rid}/console-readonly" if readonly_console else f"/rfp/{rid}"
        if ph == "devcode":
            return f"{base}?phase=devcode#rfp-phase-devcode"
        return f"{base}?phase=fs#rfp-phase-fs"
    if kind == KIND_INTEGRATION:
        base = f"/integration/{rid}/console-readonly" if readonly_console else f"/integration/{rid}"
        if ph == "devcode":
            return f"{base}?phase=devcode#int-phase-devcode"
        return f"{base}?phase=fs#int-phase-fs"
    if kind == KIND_ANALYSIS:
        base = f"/abap-analysis/{rid}/console-readonly" if readonly_console else f"/abap-analysis/{rid}"
        if ph == "devcode":
            return f"{base}#abap-phase-devcode"
        return f"{base}#abap-phase-fs"
    return "/"


def resolve_delivery_return_url(
    request_kind: str,
    request_id: int,
    return_to: str | None,
    *,
    phase: str = "fs",
    default_readonly_console: bool = False,
) -> str:
    """POST fs-start·code-start 후 리다이렉트 — return_to가 허브·콘솔 읽기 전용이면 우선."""
    s = (return_to or "").strip()
    if s.startswith("/") and ".." not in s and "//" not in s and "\n" not in s and "\r" not in s:
        for prefix in ("/rfp/", "/integration/", "/abap-analysis/"):
            if s.startswith(prefix):
                return s
    readonly = default_readonly_console or ("console-readonly" in s)
    return hub_delivery_return_path(
        request_kind, request_id, phase=phase, readonly_console=readonly
    )


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
        "fs_addendum_save_url": f"{base}/fs-addendum",
        "fs_clear_deliverable_url": f"{base}/clear-fs",
        "delivered_code_clear_url": f"{base}/clear-devcode",
    }
