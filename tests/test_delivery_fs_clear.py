"""FS·납품 코드 삭제."""

from unittest.mock import MagicMock

from app.delivery_fs_clear import clear_fs_deliverable


def test_clear_fs_resets_status_and_addendum(monkeypatch):
    row = MagicMock()
    row.fs_status = "ready"
    row.fs_text = "# FS"
    row.fs_consultant_addendum = "patch"
    row.fs_codegen_supplement_id = 1

    db = MagicMock()

    monkeypatch.setattr(
        "app.delivery_fs_clear.load_request_row",
        lambda _db, _k, _id: row,
    )
    monkeypatch.setattr(
        "app.delivery_fs_clear.list_delivery_fs_supplements",
        lambda _db, _k, _id: [],
    )

    ok, err = clear_fs_deliverable(db, "rfp", 1)
    assert ok is True
    assert err is None
    assert row.fs_status == "none"
    assert row.fs_text is None
    assert row.fs_consultant_addendum is None
    assert row.fs_codegen_supplement_id is None
    db.commit.assert_called_once()
