"""ABAP 분석·개선 — 유료 FS·납품 ABAP 백그라운드 (RFP paid_generation과 동일 패턴)."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from . import models
from .agent_playbook import PlaybookContext, STAGE_DELIVERED_ABAP, STAGE_FS_ABAP, build_playbook_addon
from .agent_display import agent_label_ko
from .agents.agent_tools import get_code_library_context
from .agents.paid_crew import generate_delivered_abap_artifact, generate_fs_markdown
from .abap_analysis_crew_adapter import abap_analysis_request_to_crew_rfp_dict, _member_safe_for_abap_analysis
from .abap_analysis_proposal_service import abap_analysis_synthetic_conversation
from .database import SessionLocal
from .delivery_fs_supplements import KIND_ANALYSIS, resolved_delivery_fs_for_codegen
from .delivery_proposal_supplements import resolved_delivery_proposal_for_downstream
from .delivered_code_package import (
    delivered_package_has_body,
    parse_delivered_code_payload,
)

_MAX_JOB_LOG_CHARS = 48_000
_DEFAULT_FS_STALE_MINUTES = 45
_DEFAULT_DC_STALE_MINUTES = 60


def _job_log_last_activity_utc(log: str | None) -> datetime | None:
    text = (log or "").strip()
    if not text:
        return None
    matches = re.findall(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\]", text)
    if not matches:
        return None
    try:
        return datetime.strptime(matches[-1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def abap_analysis_job_stale(
    row: models.AbapAnalysisRequest,
    log_field: str,
    *,
    minutes: int = _DEFAULT_FS_STALE_MINUTES,
) -> bool:
    """generating 인데 작업 로그가 오래 갱신되지 않으면 워커 중단으로 본다."""
    last = _job_log_last_activity_utc(getattr(row, log_field, None))
    if last is None:
        return True
    age_sec = (datetime.now(timezone.utc) - last).total_seconds()
    return age_sec > minutes * 60


def _abap_delivered_body_present(row: models.AbapAnalysisRequest) -> bool:
    pkg = parse_delivered_code_payload(getattr(row, "delivered_code_payload", None))
    if delivered_package_has_body(pkg):
        return True
    return bool((getattr(row, "delivered_code_text", None) or "").strip())


def reconcile_abap_analysis_delivery_status(
    db: Session,
    row: models.AbapAnalysisRequest,
    *,
    fs_stale_minutes: int = _DEFAULT_FS_STALE_MINUTES,
    dc_stale_minutes: int = _DEFAULT_DC_STALE_MINUTES,
) -> models.AbapAnalysisRequest:
    """
    FS/납품 코드 generating 상태를 DB 실제 산출물·로그와 맞춘다.
    - 본문은 있는데 status만 generating → ready
    - 오래 generating 이고 산출물 없음 → failed (재시도 가능)
    """
    changed = False
    fs_st = (getattr(row, "fs_status", None) or "none").strip()
    fs_body = (getattr(row, "fs_text", None) or "").strip()

    if fs_st == "generating":
        if fs_body:
            row.fs_status = "ready"
            row.fs_error = None
            if not getattr(row, "fs_generated_at", None):
                row.fs_generated_at = datetime.utcnow()
            changed = True
        elif abap_analysis_job_stale(row, "fs_job_log", minutes=fs_stale_minutes):
            row.fs_status = "failed"
            row.fs_error = (
                "FS 생성이 제한 시간 내에 완료되지 않았습니다. FS 생성 시작을 다시 눌러 주세요."
            )
            changed = True

    dc_st = (getattr(row, "delivered_code_status", None) or "none").strip()
    if dc_st == "generating":
        if _abap_delivered_body_present(row):
            row.delivered_code_status = "ready"
            row.delivered_code_error = None
            if not getattr(row, "delivered_code_generated_at", None):
                row.delivered_code_generated_at = datetime.utcnow()
            changed = True
        elif abap_analysis_job_stale(row, "delivered_job_log", minutes=dc_stale_minutes):
            row.delivered_code_status = "failed"
            row.delivered_code_error = (
                "개발코드 생성이 제한 시간 내에 완료되지 않았습니다. 다시 시도해 주세요."
            )
            changed = True

    if changed:
        db.commit()
        db.refresh(row)
    return row


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


def resolved_abap_analysis_fs_for_codegen(
    db: Session,
    row: models.AbapAnalysisRequest,
) -> tuple[str | None, str | None]:
    return resolved_delivery_fs_for_codegen(
        db,
        request_kind=KIND_ANALYSIS,
        request_id=int(row.id),
        agent_fs_text=getattr(row, "fs_text", None),
    )


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
            prop_merged = resolved_delivery_proposal_for_downstream(
                db,
                request_kind=KIND_ANALYSIS,
                request_id=int(row.id),
                agent_proposal_text=row.proposal_text,
            )
            row.fs_text = generate_fs_markdown(
                rfp_dict,
                conv,
                prop_merged,
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
        fs_body, fs_err = resolved_abap_analysis_fs_for_codegen(db, row)
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
            prop_merged = resolved_delivery_proposal_for_downstream(
                db,
                request_kind=KIND_ANALYSIS,
                request_id=int(row.id),
                agent_proposal_text=row.proposal_text,
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
