"""백그라운드: 유료 FS·납품 ABAP 생성."""

from __future__ import annotations

from datetime import datetime

from . import models
from .agents.paid_crew import generate_delivered_abap_markdown, generate_fs_markdown
from .database import SessionLocal
from .paid_tier import rfp_summary_for_paid


def run_fs_generation_job(rfp_id: int) -> None:
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        summ = rfp_summary_for_paid(rfp)
        prop = rfp.proposal_text or ""
        try:
            rfp.fs_text = generate_fs_markdown(summ, prop)
            rfp.fs_status = "ready"
            rfp.fs_generated_at = datetime.utcnow()
            rfp.fs_error = None
        except Exception as ex:
            rfp.fs_status = "failed"
            rfp.fs_error = str(ex)
        db.commit()
    finally:
        db.close()


def run_delivered_code_job(rfp_id: int) -> None:
    db = SessionLocal()
    try:
        rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
        if not rfp:
            return
        if not ((rfp.fs_text or "").strip()):
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = "FS 본문이 없습니다."
            db.commit()
            return
        summ = rfp_summary_for_paid(rfp)
        try:
            rfp.delivered_code_text = generate_delivered_abap_markdown(summ, rfp.fs_text or "")
            rfp.delivered_code_status = "ready"
            rfp.delivered_code_generated_at = datetime.utcnow()
            rfp.delivered_code_error = None
        except Exception as ex:
            rfp.delivered_code_status = "failed"
            rfp.delivered_code_error = str(ex)
        db.commit()
    finally:
        db.close()
