"""요청 폼 임시저장·제출 공통 검증."""

from __future__ import annotations

import unittest

from app.form_core_validation import (
    integration_missing_core_field_labels,
    rfp_missing_core_field_labels,
)


class FormCoreValidationTests(unittest.TestCase):
    def test_rfp_draft_title_only(self):
        miss = rfp_missing_core_field_labels(
            "",
            "",
            [],
            [],
            "",
            draft_minimal=True,
        )
        self.assertEqual(miss, ["요청 제목"])
        self.assertEqual(
            rfp_missing_core_field_labels(
                "제목",
                "",
                [],
                [],
                "",
                draft_minimal=True,
            ),
            [],
        )

    def test_rfp_submit_requires_core(self):
        miss = rfp_missing_core_field_labels("제목", "", [], [], "짧음")
        self.assertIn("프로그램 ID", miss)
        self.assertIn("SAP 모듈(1개 이상)", miss)

    def test_integration_draft_title_only(self):
        self.assertEqual(
            integration_missing_core_field_labels("", [], "", draft_minimal=True),
            ["요청 제목"],
        )
        self.assertEqual(
            integration_missing_core_field_labels("연동", [], "", draft_minimal=True),
            [],
        )

    def test_integration_submit_requires_impl(self):
        miss = integration_missing_core_field_labels("제목", [], "x" * 50)
        self.assertIn("구현 형태(1개 이상)", miss)


if __name__ == "__main__":
    unittest.main()
