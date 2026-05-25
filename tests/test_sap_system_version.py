"""SAP 시스템 버전 필드 검증."""

from __future__ import annotations

import unittest

from app import models
from app.sap_system_version import (
    agent_prompt_lines,
    apply_sap_system_version_to_row,
    display_label_ko,
    normalize_sap_system_version,
    sap_system_version_missing_labels,
)


class SapSystemVersionTests(unittest.TestCase):
    def test_normalize_uppercase_latin(self):
        self.assertEqual(normalize_sap_system_version("s/4hana 2023"), "S/4HANA 2023")

    def test_missing_labels_submit(self):
        self.assertEqual(sap_system_version_missing_labels("", "", required=True), ["SAP 시스템 버전"])
        self.assertEqual(sap_system_version_missing_labels("S/4HANA", "", required=False), [])

    def test_apply_to_row(self):
        row = models.RFP(user_id=1, title="t")
        err = apply_sap_system_version_to_row(row, "ecc 6.0 ehp8", "", required=True)
        self.assertIsNone(err)
        self.assertEqual(row.sap_system_version, "ECC 6.0 EHP8")

    def test_agent_prompt_s4(self):
        text = agent_prompt_lines({"sap_system_version": "S/4HANA 2023"})
        self.assertIn("S/4HANA", text)

    def test_display_free_text(self):
        self.assertEqual(display_label_ko("S/4HANA 2023", ""), "S/4HANA 2023")

    def test_display_legacy_code(self):
        self.assertIn("7.40", display_label_ko("ecc_ehp8_740", ""))


if __name__ == "__main__":
    unittest.main()
