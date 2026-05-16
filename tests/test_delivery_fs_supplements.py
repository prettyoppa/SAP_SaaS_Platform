"""컨설턴트 FS 첨부 병합·우선순위."""

from unittest.mock import MagicMock

from app import models
from app.delivery_fs_supplements import merge_agent_and_consultant_fs_markdown


def _sup(filename: str, body: str):
    s = models.RfpFsSupplement()
    s.filename = filename
    s.stored_path = "r2://test/fs.md"

    def _read(_path):
        return body.encode("utf-8")

    return s, _read


def test_merge_consultant_before_agent(monkeypatch):
    sup, _ = _sup("manual.md", "# 수동 FS\n\n본문")
    monkeypatch.setattr(
        "app.delivery_fs_supplements.r2_storage.read_bytes_from_ref",
        lambda _p: b"# manual",
    )
    text, err = merge_agent_and_consultant_fs_markdown("# agent\n\nauto", [sup])
    assert err is None
    assert text is not None
    assert "컨설턴트 FS 첨부 (코드 생성 시 **최우선**)" in text
    assert text.index("컨설턴트") < text.index("에이전트")
    assert "충돌 시 첨부 우선" in text


def test_merge_consultant_only_without_agent(monkeypatch):
    sup, _ = _sup("only.md", "# only\n\nx")
    monkeypatch.setattr(
        "app.delivery_fs_supplements.r2_storage.read_bytes_from_ref",
        lambda _p: b"# only",
    )
    text, err = merge_agent_and_consultant_fs_markdown("", [sup])
    assert err is None
    assert "컨설턴트 FS 첨부" in (text or "")


def test_merge_neither_returns_error():
    text, err = merge_agent_and_consultant_fs_markdown("", [])
    assert text is None
    assert err
