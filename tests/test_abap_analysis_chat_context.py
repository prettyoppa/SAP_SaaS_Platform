"""ABAP 분석·개선 AI 문의 — 맥락 검증(임시저장 최소 메타)."""

from unittest.mock import MagicMock

from app.routers import abap_analysis_router as mod


def _row(**kw):
    r = MagicMock()
    r.id = kw.get("id", 1)
    r.is_draft = kw.get("is_draft", True)
    r.title = kw.get("title", "")
    r.program_id = kw.get("program_id", None)
    r.requirement_text = kw.get("requirement_text", "")
    r.requirement_text_format = kw.get("requirement_text_format", "plain")
    r.reference_code_payload = kw.get("reference_code_payload", None)
    r.source_code = kw.get("source_code", "")
    r.attachments_json = kw.get("attachments_json", None)
    r.requirement_screenshots_json = kw.get("requirement_screenshots_json", None)
    return r


def test_draft_with_title_allows_chat():
    row = _row(is_draft=True, title="ZTEST 프로그램 분석")
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.first.return_value = None
    assert mod._abap_analysis_chat_context_ok(row, db) is True


def test_draft_empty_rejected():
    row = _row(is_draft=True, title="")
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.first.return_value = None
    assert mod._abap_analysis_chat_context_ok(row, db) is False


def test_submitted_without_body_rejected():
    row = _row(is_draft=False, title="제목만")
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.first.return_value = None
    assert mod._abap_analysis_chat_context_ok(row, db) is False
