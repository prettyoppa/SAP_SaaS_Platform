"""SAP 시스템 버전 필드 검증."""

from __future__ import annotations

import unittest

from app import models
from app.sap_system_version import (
    agent_prompt_lines,
    apply_sap_system_version_to_row,
    display_label_ko,
    sap_system_version_missing_labels,
)


class SapSystemVersionTests(unittest.TestCase):
    def test_missing_labels_submit(self):
        self.assertEqual(sap_system_version_missing_labels("", "", required=True), ["SAP 시스템 버전"])
        self.assertIn(
            "기타 설명",
            sap_system_version_missing_labels("other", "", required=True)[0],
        )

    def test_apply_to_row(self):
        row = models.RFP(user_id=1, title="t")
        err = apply_sap_system_version_to_row(row, "s4hana", "", required=True)
        self.assertIsNone(err)
        self.assertEqual(row.sap_system_version, "s4hana")
        self.assertIsNone(row.sap_system_version_note)

    def test_agent_prompt_ecc(self):
        text = agent_prompt_lines({"sap_system_version": "ecc740"})
        self.assertIn("ECC 7.40", text)
        self.assertIn("7.40", text)

    def test_display_other(self):
        self.assertEqual(display_label_ko("other", "NW 7.31"), "기타 (NW 7.31)")


if __name__ == "__main__":
    unittest.main()
