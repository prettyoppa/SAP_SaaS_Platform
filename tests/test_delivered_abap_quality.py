"""납품 ABAP 품질 검사·자동 보정."""

from app.delivered_abap_quality import (
    append_lint_coder_notes,
    fix_corrupted_windows_paths,
    harden_delivered_package_dict,
    harden_slot_source,
    lint_delivered_package,
    lint_fix_pass_instructions,
    lint_slot_source,
)
from app.delivered_code_package import iter_abap_delivered_zip_members


def test_lint_fix_pass_instructions_third_pass_stricter():
    third = lint_fix_pass_instructions(3)
    assert "3차" in third
    assert "error severity" in third
    second = lint_fix_pass_instructions(2)
    assert "2차" in second


def test_needs_third_lint_pass_when_issues_remain():
    from app.delivered_abap_quality import AbapLintIssue, needs_third_lint_pass

    assert not needs_third_lint_pass([])
    assert needs_third_lint_pass(
        [
            AbapLintIssue(
                severity="warning",
                slot_index=0,
                filename="t.abap",
                line_no=1,
                code="tab_char",
                message_ko="tab",
            )
        ]
    )


def test_zip_includes_cursor_workspace_md():
    pkg = {
        "program_id": "ZTEST",
        "slots": [{"filename": "ztest.abap", "role": "main_report", "source": "REPORT ztest."}],
        "coder_notes": "check TYPE string",
    }
    names = [n for n, _ in iter_abap_delivered_zip_members(pkg)]
    assert "CURSOR_WORKSPACE.md" in names
    cursor_body = next(raw.decode("utf-8") for n, raw in iter_abap_delivered_zip_members(pkg) if n == "CURSOR_WORKSPACE.md")
    assert "not included in this ZIP" in cursor_body or "ZIP에 FS는 포함되지 않음" in cursor_body


def test_append_lint_coder_notes():
    pkg = {"program_id": "Z", "slots": [], "coder_notes": "existing"}
    issues = lint_delivered_package(
        {
            "slots": [
                {"filename": "t.abap", "source": "PARAMETERS p_x TYPE string."},
            ]
        }
    )
    out = append_lint_coder_notes(pkg, issues)
    assert "정적 품질 검사 잔여" in out["coder_notes"]
    assert "existing" in out["coder_notes"]


def test_fix_windows_path_tab_corruption():
    broken = "lv_default_path = 'C:\\" + "\t" + "emp'."
    fixed, notes = fix_corrupted_windows_paths(broken)
    assert "C:\\temp" in fixed
    assert notes


def test_fix_windows_path_space_corruption():
    broken = "lv_default_path = 'C:\\   emp'."
    fixed, notes = fix_corrupted_windows_paths(broken)
    assert "temp" in fixed
    assert notes


def test_report_dedented_on_harden():
    src = "  REPORT ztest.\n  WRITE 'x'."
    out, notes = harden_slot_source(src)
    assert out.startswith("REPORT")
    assert any("dedent" in n for n in notes)


def test_lint_catches_path_before_fix():
    broken = "lv_default_path = 'C:\\" + "\t" + "emp'."
    issues = lint_slot_source(broken, filename="z.abap")
    assert any(i.code == "path_tab_corrupt" for i in issues)


def test_lint_block_balance_mismatch():
    src = "SELECT * FROM mara.\n  LOOP AT lt.\n  ENDLOOP."
    issues = lint_slot_source(src, filename="z.abap")
    assert any(i.code == "block_select" for i in issues)


def test_package_needs_second_review_on_any_issue():
    from app.delivered_abap_quality import AbapLintIssue, package_needs_second_review

    assert package_needs_second_review(
        [
            AbapLintIssue(
                severity="error",
                slot_index=0,
                filename="a.abap",
                line_no=1,
                code="tab_char",
                message_ko="x",
            )
        ]
    )
    assert not package_needs_second_review([])


def test_harden_package_applies_to_all_slots():
    data = {
        "program_id": "ZTEST",
        "slots": [
            {
                "role": "main_report",
                "filename": "z.abap",
                "title_ko": "m",
                "source": "lv_default_path = 'C:\\   emp'.",
            }
        ],
    }
    out, notes = harden_delivered_package_dict(data)
    assert "temp" in out["slots"][0]["source"]
    assert notes
