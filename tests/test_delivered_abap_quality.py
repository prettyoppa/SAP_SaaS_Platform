"""납품 ABAP 품질 검사·자동 보정."""

from app.delivered_abap_quality import (
    fix_corrupted_windows_paths,
    harden_delivered_package_dict,
    harden_slot_source,
    lint_slot_source,
)


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
