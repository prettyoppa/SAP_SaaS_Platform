"""백그라운드: 유료 FS·납품 ABAP 생성."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from sqlalchemy.orm import joinedload

from . import models
from .delivery_fs_supplements import KIND_RFP, resolved_delivery_fs_for_codegen
from .delivery_proposal_supplements import KIND_RFP as _KIND_RFP, resolved_delivery_proposal_for_downstream
from .agent_playbook import PlaybookContext, STAGE_DELIVERED_ABAP, STAGE_FS_ABAP, build_playbook_addon
from .agent_display import agent_label_ko
from .agents.agent_tools import get_code_library_context
from .agents.paid_crew import generate_delivered_abap_artifact, generate_fs_markdown
from .database import SessionLocal

_MAX_JOB_LOG_CHARS = 48_000
_HEARTBEAT_SEC = 40


def append_delivery_job_log_line(rfp_id: int, field: str, line: str) -> None:
    """워커/하트비트 스레드에서도 안전하게 쓸 수 있도록 별도 세션으로 한 줄 추가."""
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts} UTC] {line}\n"
        cur = getattr(rfp, field, None) or ""
        new = cur + entry
        if len(new) > _MAX_JOB_LOG_CHARS:
            new = new[-_MAX_JOB_LOG_CHARS:]
        setattr(rfp, field, new)
        db.commit()
    finally:
        db.close()


def _fs_heartbeat(rfp_id: int, stop: threading.Event, n_holder: dict) -> None:
    """FS설계(p_architect) 단계가 한 번에 오래 걸릴 때 주기 상태 메시지."""
    while True:
        if stop.wait(timeout=_HEARTBEAT_SEC):
            return
        n_holder["count"] += 1
        append_delivery_job_log_line(
            rfp_id,
            "fs_job_log",
            f"{agent_label_ko('p_architect')} · Gemini 호출 진행 중… (heartbeat #{n_holder['count']}, 약 {_HEARTBEAT_SEC}초마다)",
        )


def _delivered_heartbeat(
    rfp_id: int,
    stop: threading.Event,
    n_holder: dict,
    phase_hint: dict,
) -> None:
    """납품 단계별 phase_log 문자열을 공유(dict)해서, 하트비트가 같은 문구만 반복하지 않게 한다."""
    while True:
        if stop.wait(timeout=_HEARTBEAT_SEC):
            return
        n_holder["count"] += 1
        hint = (phase_hint.get("text") or "납품 코드 순차 Gemini 호출 대기 중").strip()
        if len(hint) > 140:
            hint = hint[:137] + "…"
        append_delivery_job_log_line(
            rfp_id,
            "delivered_job_log",
            f"Gemini 호출 진행 중 — 최근 단계: {hint} (heartbeat #{n_holder['count']})",
        )


def run_fs_generation_job(rfp_id: int) -> None:
    from .routers import interview_router as interview_router_module

    db = SessionLocal()
    hb_thr: threading.Thread | None = None
    hb_stop = threading.Event()

    try:
        rfp = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.messages))
            .filter(models.RFP.id == rfp_id)
            .first()
        )
        if not rfp:
            append_delivery_job_log_line(rfp_id, "fs_job_log", "오류: RFP를 찾을 수 없어 작업 종료")
            return

        append_delivery_job_log_line(rfp_id, "fs_job_log", "FS 생성 백그라운드 워커 시작")
        n_hold = {"count": 0}
        hb_thr = threading.Thread(
            target=_fs_heartbeat,
            args=(rfp_id, hb_stop, n_hold),
            daemon=True,
        )
        hb_thr.start()

        append_delivery_job_log_line(rfp_id, "fs_job_log", "RFP·메시지 로드 완료, 컨텍스트 빌드 중")
        rfp_dict = interview_router_module._rfp_to_dict(rfp)
        conv = interview_router_module._conversation_list_for_llm(rfp)
        ms = interview_router_module._member_safe_for_rfp(db, rfp)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        append_delivery_job_log_line(
            rfp_id,
            "fs_job_log",
            f"{agent_label_ko('p_architect')}(Gemini) 호출 직전 · 수 분 걸릴 수 있음",
        )
        wo = (getattr(rfp, "workflow_origin", None) or "direct").strip()
        pb_fs = build_playbook_addon(db, PlaybookContext(entity="rfp", stage=STAGE_FS_ABAP, workflow_origin=wo))
        try:
            prop_merged = resolved_delivery_proposal_for_downstream(
                db,
                request_kind=_KIND_RFP,
                request_id=int(rfp.id),
                agent_proposal_text=rfp.proposal_text,
            )
            rfp.fs_text = generate_fs_markdown(
                rfp_dict,
                conv,
                prop_merged,
                code_library_context=code_ctx or "",
                member_safe_output=ms,
                playbook_addon=pb_fs,
            )
            rfp.fs_status = "ready"
            rfp.fs_generated_at = datetime.utcnow()
            rfp.fs_error = None
            append_delivery_job_log_line(rfp_id, "fs_job_log", f"{agent_label_ko('p_architect')} 완료 · fs_text 저장")
        except Exception as ex:
            rfp.fs_status = "failed"
            rfp.fs_error = str(ex)
            append_delivery_job_log_line(rfp_id, "fs_job_log", f"실패: {type(ex).__name__}: {ex}")
        db.commit()
    finally:
        hb_stop.set()
        if hb_thr is not None:
            hb_thr.join(timeout=2)
        db.close()


def resolved_fs_markdown_for_codegen(db, rfp: models.RFP) -> tuple[str | None, str | None]:
    """ABAP 코드 생성에 쓸 FS 본문 (에이전트 FS + 컨설턴트 첨부, 첨부 우선)."""
    return resolved_delivery_fs_for_codegen(
        db,
        request_kind=KIND_RFP,
        request_id=int(rfp.id),
        agent_fs_text=rfp.fs_text,
    )


def run_delivered_code_job(rfp_id: int) -> None:
    from .routers import interview_router as interview_router_module

    db = SessionLocal()
    hb_thr: threading.Thread | None = None
    hb_stop = threading.Event()

    try:
        rfp = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.messages))
            .filter(models.RFP.id == rfp_id)
            .first()
        )
        if not rfp:
            append_delivery_job_log_line(rfp_id, "delivered_job_log", "오류: RFP를 찾을 수 없어 작업 종료")
            return

        append_delivery_job_log_line(rfp_id, "delivered_job_log", "납품 ABAP 생성 백그라운드 워커 시작")
        append_delivery_job_log_line(rfp_id, "delivered_job_log", "RFP·메시지 로드, 코드 생성용 FS 해석 중")
        fs_body, fs_err = resolved_fs_markdown_for_codegen(db, rfp)
        if fs_err or not (fs_body or "").strip():
            msg = fs_err or "FS 본문이 없습니다."
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = msg
            append_delivery_job_log_line(rfp_id, "delivered_job_log", f"중단: {msg}")
            db.commit()
            return

        from .delivery_fs_supplements import list_delivery_fs_supplements

        n_sup = len(list_delivery_fs_supplements(db, KIND_RFP, int(rfp.id)))
        append_delivery_job_log_line(
            rfp_id,
            "delivered_job_log",
            f"코드 생성용 FS 본문 준비 완료 (약 {len(fs_body.strip())}자, 컨설턴트 첨부 {n_sup}건)",
        )

        n_hold = {"count": 0}
        phase_hint = {"text": ""}

        def _phase_log_delivery(m: str) -> None:
            phase_hint["text"] = (m or "").strip()
            append_delivery_job_log_line(rfp_id, "delivered_job_log", m)

        hb_thr = threading.Thread(
            target=_delivered_heartbeat,
            args=(rfp_id, hb_stop, n_hold, phase_hint),
            daemon=True,
        )
        hb_thr.start()

        rfp_dict = interview_router_module._rfp_to_dict(rfp)
        conv = interview_router_module._conversation_list_for_llm(rfp)
        ms = interview_router_module._member_safe_for_rfp(db, rfp)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        wo_d = (getattr(rfp, "workflow_origin", None) or "direct").strip()
        pb_del = build_playbook_addon(
            db, PlaybookContext(entity="rfp", stage=STAGE_DELIVERED_ABAP, workflow_origin=wo_d)
        )
        try:
            prop_merged = resolved_delivery_proposal_for_downstream(
                db,
                request_kind=_KIND_RFP,
                request_id=int(rfp.id),
                agent_proposal_text=rfp.proposal_text,
            )
            pkg, legacy_md = generate_delivered_abap_artifact(
                rfp_dict,
                fs_body or "",
                prop_merged,
                conv,
                code_library_context=code_ctx or "",
                member_safe_output=ms,
                phase_log=_phase_log_delivery,
                playbook_addon=pb_del,
            )
            rfp.delivered_code_text = legacy_md
            rfp.delivered_code_payload = json.dumps(pkg, ensure_ascii=False) if pkg else None
            rfp.delivered_code_status = "ready"
            rfp.delivered_code_generated_at = datetime.utcnow()
            rfp.delivered_code_error = None
            append_delivery_job_log_line(
                rfp_id,
                "delivered_job_log",
                "납품 코드 생성 완료 · 결과 저장",
            )
        except Exception as ex:
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = str(ex)
            append_delivery_job_log_line(
                rfp_id,
                "delivered_job_log",
                f"실패: {type(ex).__name__}: {ex}",
            )
        db.commit()
    finally:
        hb_stop.set()
        if hb_thr is not None:
            hb_thr.join(timeout=2)
        db.close()
