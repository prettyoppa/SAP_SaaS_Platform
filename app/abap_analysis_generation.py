"""ABAP 분석·개선 — 유료 FS·납품 ABAP 백그라운드 (RFP paid_generation과 동일 패턴)."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from sqlalchemy.orm import joinedload

from . import models
from .agent_playbook import PlaybookContext, STAGE_DELIVERED_ABAP, STAGE_FS_ABAP, build_playbook_addon
from .agent_display import agent_label_ko
from .agents.agent_tools import get_code_library_context
from .agents.paid_crew import generate_delivered_abap_artifact, generate_fs_markdown
from .abap_analysis_crew_adapter import abap_analysis_request_to_crew_rfp_dict, _member_safe_for_abap_analysis
from .abap_analysis_proposal_service import abap_analysis_synthetic_conversation
from .database import SessionLocal

_MAX_JOB_LOG_CHARS = 48_000


def append_abap_analysis_job_log(analysis_id: int, field: str, line: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == analysis_id).first()
        if not row:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts} UTC] {line}\n"
        cur = getattr(row, field, None) or ""
        new = cur + entry
        if len(new) > _MAX_JOB_LOG_CHARS:
            new = new[-_MAX_JOB_LOG_CHARS:]
        setattr(row, field, new)
        db.commit()
    finally:
        db.close()


def _fs_heartbeat_abap(analysis_id: int, stop: threading.Event, n_holder: dict) -> None:
    while True:
        if stop.wait(timeout=40):
            return
        n_holder["count"] += 1
        append_abap_analysis_job_log(
            analysis_id,
            "fs_job_log",
            f"{agent_label_ko('p_architect')} · Gemini 호출 진행 중… (heartbeat #{n_holder['count']})",
        )


def _delivered_heartbeat_abap(
    analysis_id: int,
    stop: threading.Event,
    n_holder: dict,
    phase_hint: dict,
) -> None:
    while True:
        if stop.wait(timeout=40):
            return
        n_holder["count"] += 1
        hint = (phase_hint.get("text") or "납품 코드 순차 Gemini 호출 대기 중").strip()
        if len(hint) > 140:
            hint = hint[:137] + "…"
        append_abap_analysis_job_log(
            analysis_id,
            "delivered_job_log",
            f"Gemini 호출 진행 중 — 최근 단계: {hint} (heartbeat #{n_holder['count']})",
        )


def resolved_abap_analysis_fs_for_codegen(row: models.AbapAnalysisRequest) -> tuple[str | None, str | None]:
    body = (getattr(row, "fs_text", None) or "").strip()
    if not body:
        return None, "FS 본문이 없습니다. 관리자 화면에서 FS 생성을 완료하세요."
    return body, None


def run_abap_analysis_fs_job(analysis_id: int) -> None:
    db = SessionLocal()
    hb_thr: threading.Thread | None = None
    hb_stop = threading.Event()

    try:
        row = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.followup_messages))
            .filter(models.AbapAnalysisRequest.id == analysis_id)
            .first()
        )
        if not row:
            append_abap_analysis_job_log(analysis_id, "fs_job_log", "오류: 분석 요청을 찾을 수 없어 작업 종료")
            return

        append_abap_analysis_job_log(analysis_id, "fs_job_log", "FS 생성 백그라운드 워커 시작")
        n_hold = {"count": 0}
        hb_thr = threading.Thread(
            target=_fs_heartbeat_abap,
            args=(analysis_id, hb_stop, n_hold),
            daemon=True,
        )
        hb_thr.start()

        rfp_dict = abap_analysis_request_to_crew_rfp_dict(db, row)
        conv = abap_analysis_synthetic_conversation(row)
        ms = _member_safe_for_abap_analysis(db, row)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        append_abap_analysis_job_log(
            analysis_id,
            "fs_job_log",
            f"{agent_label_ko('p_architect')}(Gemini) 호출 직전 · 수 분 걸릴 수 있음",
        )
        pb_fs = build_playbook_addon(
            db,
            PlaybookContext(entity="abap_analysis", stage=STAGE_FS_ABAP, workflow_origin="abap_analysis"),
        )
        try:
            row.fs_text = generate_fs_markdown(
                rfp_dict,
                conv,
                row.proposal_text or "",
                code_library_context=code_ctx or "",
                member_safe_output=ms,
                playbook_addon=pb_fs,
            )
            row.fs_status = "ready"
            row.fs_generated_at = datetime.utcnow()
            row.fs_error = None
            append_abap_analysis_job_log(analysis_id, "fs_job_log", f"{agent_label_ko('p_architect')} 완료 · fs_text 저장")
        except Exception as ex:
            row.fs_status = "failed"
            row.fs_error = str(ex)
            append_abap_analysis_job_log(analysis_id, "fs_job_log", f"실패: {type(ex).__name__}: {ex}")
        db.commit()
    finally:
        hb_stop.set()
        if hb_thr is not None:
            hb_thr.join(timeout=2)
        db.close()


def run_abap_analysis_delivered_code_job(analysis_id: int) -> None:
    db = SessionLocal()
    hb_thr: threading.Thread | None = None
    hb_stop = threading.Event()

    try:
        row = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.followup_messages))
            .filter(models.AbapAnalysisRequest.id == analysis_id)
            .first()
        )
        if not row:
            append_abap_analysis_job_log(analysis_id, "delivered_job_log", "오류: 분석 요청을 찾을 수 없어 작업 종료")
            return

        append_abap_analysis_job_log(analysis_id, "delivered_job_log", "납품 ABAP 생성 백그라운드 워커 시작")
        fs_body, fs_err = resolved_abap_analysis_fs_for_codegen(row)
        if fs_err or not (fs_body or "").strip():
            msg = fs_err or "FS 본문이 없습니다."
            row.delivered_code_status = "failed"
            row.delivered_code_error = msg
            append_abap_analysis_job_log(analysis_id, "delivered_job_log", f"중단: {msg}")
            db.commit()
            return

        n_hold = {"count": 0}
        phase_hint = {"text": ""}

        def _phase_log_delivery(m: str) -> None:
            phase_hint["text"] = (m or "").strip()
            append_abap_analysis_job_log(analysis_id, "delivered_job_log", m)

        hb_thr = threading.Thread(
            target=_delivered_heartbeat_abap,
            args=(analysis_id, hb_stop, n_hold, phase_hint),
            daemon=True,
        )
        hb_thr.start()

        rfp_dict = abap_analysis_request_to_crew_rfp_dict(db, row)
        conv = abap_analysis_synthetic_conversation(row)
        ms = _member_safe_for_abap_analysis(db, row)
        code_ctx = get_code_library_context(
            db,
            rfp_dict.get("sap_modules", []),
            rfp_dict.get("dev_types", []),
            member_safe_output=ms,
        )
        pb_del = build_playbook_addon(
            db,
            PlaybookContext(entity="abap_analysis", stage=STAGE_DELIVERED_ABAP, workflow_origin="abap_analysis"),
        )
        try:
            pkg, legacy_md = generate_delivered_abap_artifact(
                rfp_dict,
                fs_body or "",
                row.proposal_text or "",
                conv,
                code_library_context=code_ctx or "",
                member_safe_output=ms,
                phase_log=_phase_log_delivery,
                playbook_addon=pb_del,
            )
            row.delivered_code_text = legacy_md
            row.delivered_code_payload = json.dumps(pkg, ensure_ascii=False) if pkg else None
            row.delivered_code_status = "ready"
            row.delivered_code_generated_at = datetime.utcnow()
            row.delivered_code_error = None
            append_abap_analysis_job_log(analysis_id, "delivered_job_log", "납품 코드 생성 완료 · 결과 저장")
        except Exception as ex:
            row.delivered_code_status = "failed"
            row.delivered_code_error = str(ex)
            append_abap_analysis_job_log(
                analysis_id,
                "delivered_job_log",
                f"실패: {type(ex).__name__}: {ex}",
            )
        db.commit()
    finally:
        hb_stop.set()
        if hb_thr is not None:
            hb_thr.join(timeout=2)
        db.close()
