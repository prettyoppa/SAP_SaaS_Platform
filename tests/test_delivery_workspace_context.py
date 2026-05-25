"""납품 작업실 — 멀티 슬롯 읽기 컨텍스트."""

from __future__ import annotations

import unittest

from app.delivery_workspace_context import build_peer_sources_context, peer_abap_slot_indices


class DeliveryWorkspaceContextTests(unittest.TestCase):
    def test_includes_main_first(self):
        slots = [
            {"filename": "zinc.abap", "role": "include", "source": "DATA a."},
            {"filename": "zmain.abap", "role": "main_report", "source": "REPORT z."},
        ]
        idx = peer_abap_slot_indices(slots, active_index=0)
        self.assertEqual(idx, [1])
        ctx, n = build_peer_sources_context(slots, active_index=0)
        self.assertEqual(n, 1)
        self.assertIn("zmain.abap", ctx)
        self.assertIn("REPORT z.", ctx)

    def test_excludes_active_slot(self):
        slots = [
            {"filename": "zmain.abap", "role": "main_report", "source": "REPORT z."},
            {"filename": "zinc.abap", "role": "include", "source": "DATA a."},
        ]
        ctx, n = build_peer_sources_context(slots, active_index=0)
        self.assertEqual(n, 1)
        self.assertIn("zinc.abap", ctx)
        self.assertNotIn("REPORT z.", ctx)


if __name__ == "__main__":
    unittest.main()
