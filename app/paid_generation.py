"""백그라운드: 유료 FS·납품 ABAP 생성."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import joinedload

from . import models, r2_storage
from .agents.agent_tools import get_code_library_context
from .agents.paid_crew import generate_delivered_abap_markdown, generate_fs_markdown
from .database import SessionLocal


def run_fs_generation_job(rfp_id: int) -> None:
    from .routers import interview_router as interview_router_module

    db = SessionLocal()
    try:
        rfp = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.messages))
            .filter(models.RFP.id == rfp_id)
            .first()
        )
        if not rfp:
            return
        rfp_dict = interview_router_module._rfp_to_dict(rfp)
        conv = interview_router_module._conversation_list_for_llm(rfp)
        ms = interview_router_module._member_safe_for_rfp(db, rfp)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        try:
            rfp.fs_text = generate_fs_markdown(
                rfp_dict,
                conv,
                rfp.proposal_text or "",
                code_library_context=code_ctx or "",
                member_safe_output=ms,
            )
            rfp.fs_status = "ready"
            rfp.fs_generated_at = datetime.utcnow()
            rfp.fs_error = None
        except Exception as ex:
            rfp.fs_status = "failed"
            rfp.fs_error = str(ex)
        db.commit()
    finally:
        db.close()


def resolved_fs_markdown_for_codegen(db, rfp: models.RFP) -> tuple[str | None, str | None]:
    """
    ABAP 코드 생성에 쓸 FS 본문.
    관리자가 보조 .md를 선택(fs_codegen_supplement_id)했으면 해당 파일, 아니면 에이전트 fs_text.
    반환 (text, None) 또는 (None, error_message).
    """
    sid = getattr(rfp, "fs_codegen_supplement_id", None)
    if sid:
        sup = (
            db.query(models.RfpFsSupplement)
            .filter(
                models.RfpFsSupplement.id == sid,
                models.RfpFsSupplement.rfp_id == rfp.id,
            )
            .first()
        )
        if not sup:
            return None, "선택된 FS 첨부가 없거나 만료되었습니다."
        raw = r2_storage.read_bytes_from_ref(sup.stored_path)
        if raw is None:
            return None, "FS 첨부 파일을 읽을 수 없습니다(스토리지 경로를 확인하세요)."
        try:
            return raw.decode("utf-8"), None
        except Exception:
            return raw.decode("utf-8", errors="replace"), None
    txt = (rfp.fs_text or "").strip()
    if not txt:
        return None, "FS 본문이 없습니다. 에이전트 FS 생성을 완료하거나 컨설턴트 FS .md를 첨부하고 선택하세요."
    return rfp.fs_text or "", None


def run_delivered_code_job(rfp_id: int) -> None:
    from .routers import interview_router as interview_router_module

    db = SessionLocal()
    try:
        rfp = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.messages))
            .filter(models.RFP.id == rfp_id)
            .first()
        )
        if not rfp:
            return
        fs_body, fs_err = resolved_fs_markdown_for_codegen(db, rfp)
        if fs_err or not (fs_body or "").strip():
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = fs_err or "FS 본문이 없습니다."
            db.commit()
            return
        rfp_dict = interview_router_module._rfp_to_dict(rfp)
        conv = interview_router_module._conversation_list_for_llm(rfp)
        ms = interview_router_module._member_safe_for_rfp(db, rfp)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        try:
            rfp.delivered_code_text = generate_delivered_abap_markdown(
                rfp_dict,
                fs_body or "",
                rfp.proposal_text or "",
                conv,
                code_library_context=code_ctx or "",
                member_safe_output=ms,
            )
            rfp.delivered_code_status = "ready"
            rfp.delivered_code_generated_at = datetime.utcnow()
            rfp.delivered_code_error = None
        except Exception as ex:
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = str(ex)
        db.commit()
    finally:
        db.close()
