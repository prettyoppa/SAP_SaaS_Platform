"""납품 구현 보완 작업실 — 접근·작업본 fork·공식 payload 불변."""

from __future__ import annotations

import json
import unittest

from app import models
from app.database import Base, SessionLocal, engine
from app.delivery_fs_supplements import KIND_RFP
from app.delivery_workspace import (
    apply_slot_source,
    get_official_package,
    get_working_package,
    normalize_request_kind,
    parse_package,
)
from app.delivered_code_package import delivered_package_has_body, normalize_delivered_package
from app.delivery_workspace_access import user_can_use_delivery_workspace
from app.delivery_workspace_display import workspace_enabled_for_kind, workspace_page_header
from app.delivery_workspace_ai import extract_suggested_abap


def _sample_pkg() -> dict:
    return {
        "program_id": "ZTEST",
        "slots": [
            {
                "filename": "ztest_top.abap",
                "role": "top",
                "source": "REPORT ztest.",
                "title_ko": "TOP",
            }
        ],
        "implementation_guide_md": "guide",
        "se38_implementation_guide_md": "se38",
        "test_scenarios_md": "tests",
    }


def _normalized_sample_json() -> str:
    pkg = normalize_delivered_package(_sample_pkg())
    assert pkg is not None
    return json.dumps(pkg, ensure_ascii=False)


class DeliveryWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from app.main import _run_migrations

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        _run_migrations()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_extract_suggested_abap_fence(self):
        raw = "설명\n```abap\nREPORT zfix.\n```\n"
        self.assertEqual(extract_suggested_abap(raw), "REPORT zfix.")

    def test_workspace_not_enabled_for_integration(self):
        self.assertTrue(workspace_enabled_for_kind("rfp"))
        self.assertTrue(workspace_enabled_for_kind("analysis"))
        self.assertFalse(workspace_enabled_for_kind("integration"))

    def test_workspace_page_header_uses_title(self):
        class _Row:
            id = 14
            title = "SAP 표준 소스 다운로드"
            created_at = None

        h = workspace_page_header(_Row(), "rfp")
        self.assertEqual(h["workspace_header_title"], "SAP 표준 소스 다운로드")
        self.assertEqual(h["workspace_request_no_prefix"], "RFP")

    def test_normalize_request_kind_aliases(self):
        self.assertEqual(normalize_request_kind("rfp"), KIND_RFP)
        pkg = normalize_delivered_package(_sample_pkg())
        self.assertTrue(delivered_package_has_body(pkg))

    def test_user_can_use_delivery_workspace_owner_consultant(self):
        consultant = models.User(
            email="c@example.com",
            full_name="C",
            hashed_password="x",
            is_consultant=True,
        )
        member = models.User(
            email="m@example.com",
            full_name="M",
            hashed_password="x",
            is_consultant=False,
        )
        self.db.add_all([consultant, member])
        self.db.commit()
        pkg = json.dumps(_sample_pkg(), ensure_ascii=False)
        rfp = models.RFP(
            user_id=int(consultant.id),
            title="t",
            delivered_code_status="ready",
            delivered_code_payload=pkg,
        )
        self.db.add(rfp)
        self.db.commit()
        self.db.refresh(rfp)
        self.assertTrue(
            user_can_use_delivery_workspace(
                self.db,
                consultant,
                request_kind=KIND_RFP,
                request_id=int(rfp.id),
                owner_user_id=int(consultant.id),
                entity=rfp,
            )
        )
        self.assertFalse(
            user_can_use_delivery_workspace(
                self.db,
                member,
                request_kind=KIND_RFP,
                request_id=int(rfp.id),
                owner_user_id=int(consultant.id),
                entity=rfp,
            )
        )

    def test_working_copy_forks_without_mutating_official(self):
        consultant = models.User(
            email="c2@example.com",
            full_name="C2",
            hashed_password="x",
            is_consultant=True,
        )
        self.db.add(consultant)
        self.db.commit()
        rfp = models.RFP(
            user_id=int(consultant.id),
            title="t",
            delivered_code_status="ready",
            delivered_code_payload=_normalized_sample_json(),
        )
        self.db.add(rfp)
        self.db.commit()
        self.db.refresh(rfp)

        working = get_working_package(self.db, rfp, KIND_RFP)
        self.assertIsNotNone(working)
        self.assertEqual(working["slots"][0]["source"], "REPORT ztest.")

        apply_slot_source(self.db, rfp, KIND_RFP, 0, "REPORT zfix.")
        self.db.commit()
        self.db.refresh(rfp)

        off = get_official_package(rfp, KIND_RFP)
        self.assertEqual(off["slots"][0]["source"], "REPORT ztest.")
        work2 = parse_package(rfp.delivered_code_working_payload, KIND_RFP)
        self.assertEqual(work2["slots"][0]["source"], "REPORT zfix.")


if __name__ == "__main__":
    unittest.main()
