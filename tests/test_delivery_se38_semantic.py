"""SE38 semantic lint + fix context tests."""

from app.delivered_abap_quality import lint_se38_semantic_patterns, lint_slot_source
from app.delivery_workspace_fix_context import build_full_package_abap_context


def test_lint_param_type_string():
    src = "PARAMETERS p_path TYPE string."
    issues = lint_se38_semantic_patterns(src, filename="top.abap")
    assert any(i.code == "param_type_string" for i in issues)


def test_lint_type_boolean():
    src = "DATA lv TYPE boolean."
    issues = lint_se38_semantic_patterns(src, filename="top.abap")
    assert any(i.code == "type_boolean" for i in issues)


def test_lint_dir_sep():
    src = "lv_sep = cl_abap_char_utilities=>dir_sep."
    issues = lint_se38_semantic_patterns(src, filename="forms.abap")
    assert any(i.code == "dir_sep_invalid" for i in issues)


def test_lint_gui_download_xstring():
    src = "CALL FUNCTION 'GUI_DOWNLOAD' EXPORTING xstring = lv_x."
    issues = lint_se38_semantic_patterns(src, filename="forms.abap")
    assert any(i.code == "gui_download_xstring" for i in issues)


def test_lint_salv_checkbox():
    src = "lo_col->set_cell_type( if_salv_c_cell_type=>checkbox )."
    issues = lint_se38_semantic_patterns(src, filename="pbo.abap")
    assert any(i.code == "salv_checkbox_type" for i in issues)


def test_full_package_context_includes_all_slots():
    long_main = "REPORT z.\n" + ("WRITE 'x'.\n" * 50)
    slots = [
        {"filename": "zinc.abap", "role": "include", "source": "INCLUDE ztop." * 5},
        {"filename": "zmain.abap", "role": "main_report", "source": long_main},
    ]
    ctx, n = build_full_package_abap_context(slots, active_index=0, max_total_chars=50_000)
    assert n == 2
    assert "SE38 오류 보고 위치" in ctx
    assert "zmain.abap" in ctx
    assert "zinc.abap" in ctx
    assert long_main[:20] in ctx


def test_slot_source_includes_semantic_lint():
    src = "PARAMETERS p_x TYPE string."
    issues = lint_slot_source(src, filename="t.abap")
    assert any(i.code == "param_type_string" for i in issues)
