"""납품 작업실 — 소스 diff."""

from __future__ import annotations

import unittest

from app.delivery_workspace_diff import (
    collapse_diff_rows,
    compute_line_diff_rows,
    diff_panel_html,
    render_diff_html,
)


class DeliveryWorkspaceDiffTests(unittest.TestCase):
    def test_insert_delete(self):
        old = "A\nB\nC\n"
        new = "A\nX\nC\n"
        rows = compute_line_diff_rows(old, new)
        kinds = [r["kind"] for r in rows]
        self.assertIn("delete", kinds)
        self.assertIn("insert", kinds)

    def test_collapse_unchanged(self):
        old = "\n".join(f"L{i}" for i in range(20))
        new = old + "\nTAIL"
        rows = collapse_diff_rows(compute_line_diff_rows(old, new))
        self.assertTrue(any(r.get("kind") == "gap" for r in rows))

    def test_render_html_escapes(self):
        html_out = render_diff_html(
            [{"kind": "insert", "text": "<script>", "old_no": None, "new_no": 1}]
        )
        self.assertIn("&lt;script&gt;", html_out)
        self.assertNotIn("<script>", html_out)

    def test_diff_panel(self):
        out = diff_panel_html("OLD\n", "NEW\n")
        self.assertIn("dw-diff-line", out)


if __name__ == "__main__":
    unittest.main()
