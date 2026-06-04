"""SE38 작업실 — 오류·구문 집중 힌트."""

from app.delivery_workspace_se38_focus import (
    build_se38_focus_section,
    extract_consultant_snippet,
    find_snippet_anchor_line,
)


def test_extract_consultant_snippet_from_pasted_call():
    err = """
CALL METHOD cl_gui_frontend_services=>file_save_dialog
  CHANGING
    rc = lv_rc.

위 구문에서 아래 syntax error:
Formal parameter "RC" does not exist.
"""
    snip = extract_consultant_snippet(err)
    assert "file_save_dialog" in snip.lower()
    assert "rc" in snip.lower()


def test_find_anchor_line_for_file_save_dialog():
    src = "\n".join(
        [
            "REPORT ztest.",
            "FORM foo.",
            "  CALL METHOD cl_gui_frontend_services=>file_save_dialog",
            "    CHANGING rc = lv_rc.",
            "ENDFORM.",
        ]
    )
    snip = "CALL METHOD cl_gui_frontend_services=>file_save_dialog"
    assert find_snippet_anchor_line(snip, src) == 3


def test_build_focus_section_mentions_rc_exporting_hint():
    err = 'Formal parameter "RC" does not exist.\nfile_save_dialog'
    block = build_se38_focus_section(err, "CALL METHOD cl_gui_frontend_services=>file_save_dialog.")
    assert "EXPORTING" in block
    assert "이번 SE38" in block
