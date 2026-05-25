"""납품 작업실 — 제안 검증."""

from __future__ import annotations

import unittest

from app.delivery_workspace_validation import (
    cross_slot_fix_hints,
    line_number_gutter,
    parse_fix_elsewhere_marker,
    slot_is_include_like,
    suggestion_defers_fix_elsewhere,
    validate_suggested_against_original,
)


class DeliveryWorkspaceValidationTests(unittest.TestCase):
    def test_blocks_shorter_suggestion(self):
        orig = "\n".join(f"line {i}" for i in range(1, 101))
        sug = "\n".join(f"fix {i}" for i in range(1, 11))
        v = validate_suggested_against_original(orig, sug)
        self.assertFalse(v.ok)
        self.assertIn("source_shorter", v.warn_codes)

    def test_allows_similar_length(self):
        orig = "REPORT z.\nINCLUDE ztop.\nEND.\n"
        sug = "REPORT z.\nINCLUDE ztop.\nDATA x.\nEND.\n"
        v = validate_suggested_against_original(orig, sug, slot_role="main_report")
        self.assertTrue(v.ok)

    def test_line_gutter(self):
        g = line_number_gutter("a\nb\n")
        self.assertIn("1", g)
        self.assertIn("2", g)

    def test_cross_slot_hints(self):
        slots = [
            {"filename": "zmain.abap"},
            {"filename": "zinc_top.abap"},
        ]
        hints = cross_slot_fix_hints("Include ZINC_TOP not found", slots, active_index=0)
        self.assertIn("zinc_top.abap", hints)

    def test_include_like_role(self):
        self.assertTrue(slot_is_include_like("include"))
        self.assertFalse(slot_is_include_like("main_report"))

    def test_defer_fix_elsewhere(self):
        orig = "INCLUDE ztop.\nDATA x.\n"
        sug = (
            "* DW-FIX-ELSEWHERE: 수정 대상=zmain.abap | 이유=INCLUDE 문 오류\n"
            + orig
        )
        deferred, target, _ = suggestion_defers_fix_elsewhere(sug, orig)
        self.assertTrue(deferred)
        self.assertEqual(parse_fix_elsewhere_marker(sug)[0], "zmain.abap")
        self.assertEqual(target, "zmain.abap")


if __name__ == "__main__":
    unittest.main()
