"""분석개선 FS/납품 generating 상태 복구."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app import models
from app.abap_analysis_generation import (
    abap_analysis_job_stale,
    reconcile_abap_analysis_delivery_status,
)


def _fake_row(**kwargs):
    row = models.AbapAnalysisRequest()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def test_reconcile_fs_generating_with_body_becomes_ready():
    db = MagicMock()
    row = _fake_row(fs_status="generating", fs_text="# FS\n\n본문", fs_error="old")
    reconcile_abap_analysis_delivery_status(db, row, fs_stale_minutes=45)
    assert row.fs_status == "ready"
    assert row.fs_error is None
    assert row.fs_generated_at is not None
    db.commit.assert_called_once()


def test_reconcile_fs_stale_without_body_becomes_failed():
    db = MagicMock()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    log = f"[{old} UTC] heartbeat\n"
    row = _fake_row(fs_status="generating", fs_text="", fs_job_log=log)
    reconcile_abap_analysis_delivery_status(db, row, fs_stale_minutes=45)
    assert row.fs_status == "failed"
    assert "제한 시간" in (row.fs_error or "")
    db.commit.assert_called_once()


def test_abap_analysis_job_stale_no_log():
    row = _fake_row(fs_job_log=None)
    assert abap_analysis_job_stale(row, "fs_job_log", minutes=20) is True
