"""SE38 작업실 AI 수정 제안 이력 — 중복 제안 감지."""

import unittest

from app.delivery_workspace_fix_history import (
    WORKSPACE_FIX_HISTORY_KEY,
    append_fix_history,
    format_fix_history_for_prompt,
    get_fix_history,
    suggestion_already_attempted,
)


class DeliveryWorkspaceFixHistoryTests(unittest.TestCase):
    def test_append_and_get_history(self):
        pkg: dict = {}
        append_fix_history(
            pkg,
            slot_index=0,
            se38_error="Syntax error in line 12",
            source_before="REPORT ztest.",
            suggested="REPORT ztest.\nDATA lv TYPE i.",
        )
        hist = get_fix_history(pkg)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["slot_index"], 0)
        self.assertIn(WORKSPACE_FIX_HISTORY_KEY, pkg)

    def test_suggestion_already_attempted_same_hash(self):
        pkg: dict = {}
        suggested = "REPORT ztest.\nDATA lv TYPE i."
        append_fix_history(
            pkg,
            slot_index=1,
            se38_error="Syntax error",
            source_before="REPORT ztest.",
            suggested=suggested,
        )
        hist = get_fix_history(pkg)
        self.assertTrue(
            suggestion_already_attempted(
                hist, slot_index=1, suggested=suggested, se38_error="Syntax error"
            )
        )
        self.assertFalse(
            suggestion_already_attempted(
                hist,
                slot_index=1,
                suggested="REPORT ztest.\nDATA lv2 TYPE i.",
                se38_error="Syntax error",
            )
        )

    def test_format_fix_history_for_prompt_includes_block(self):
        pkg: dict = {}
        append_fix_history(
            pkg,
            slot_index=0,
            se38_error="Line 5: unknown field",
            source_before="REPORT z.",
            suggested="REPORT z.\nDATA x TYPE i.",
        )
        block = format_fix_history_for_prompt(
            get_fix_history(pkg), slot_index=0, se38_error="Line 5: unknown field"
        )
        self.assertIn("이전 AI 수정 시도", block)
        self.assertIn("동일 패치 재출력 금지", block)


if __name__ == "__main__":
    unittest.main()
