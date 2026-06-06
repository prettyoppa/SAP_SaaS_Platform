"""납품 구현 보완 작업실 — 접근·작업본 fork·공식 payload 불변."""

from __future__ import annotations

import json
import unittest

from app import models
from app.database import Base, SessionLocal, engine
from app.delivery_fs_supplements import KIND_RFP
from app.delivery_fs_clear import clear_delivered_code_deliverable
from app.delivery_workspace import (
    apply_slot_source,
    clear_delivered_code_working_copy,
    clear_pending_suggestion,
    get_official_package,
    get_pending_suggestion,
    get_working_package,
    has_delivered_code_working_copy,
    normalize_request_kind,
    parse_package,
    set_pending_suggestion,
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

    def test_workspace_closed_for_all_kinds(self):
        self.assertFalse(workspace_enabled_for_kind("rfp"))
        self.assertFalse(workspace_enabled_for_kind("analysis"))
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
        self.assertFalse(
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

    def test_pending_suggestion_persists_in_working_payload(self):
        consultant = models.User(
            email="c3@example.com",
            full_name="C3",
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

        big_src = "REPORT ztest.\n" + ("  WRITE 'x'.\n" * 400)
        set_pending_suggestion(
            self.db,
            rfp,
            KIND_RFP,
            0,
            suggested_source=big_src,
            se38_error="Formal parameter RC does not exist.",
            peer_count=2,
        )
        self.db.commit()
        self.db.refresh(rfp)

        pkg = get_working_package(self.db, rfp, KIND_RFP)
        pending = get_pending_suggestion(pkg, 0)
        self.assertIsNotNone(pending)
        self.assertIn("WRITE 'x'", pending["suggested_source"])
        self.assertEqual(pending["se38_error"], "Formal parameter RC does not exist.")
        self.assertEqual(pending["peer_count"], 2)

        clear_pending_suggestion(self.db, rfp, KIND_RFP)
        self.db.commit()
        pkg2 = get_working_package(self.db, rfp, KIND_RFP)
        self.assertIsNone(get_pending_suggestion(pkg2, 0))

    def test_clear_working_copy_only(self):
        consultant = models.User(
            email="c4@example.com",
            full_name="C4",
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

        get_working_package(self.db, rfp, KIND_RFP)
        self.db.commit()
        self.db.refresh(rfp)
        self.assertTrue(has_delivered_code_working_copy(rfp))

        self.assertTrue(clear_delivered_code_working_copy(rfp))
        self.db.commit()
        self.db.refresh(rfp)
        self.assertFalse(has_delivered_code_working_copy(rfp))
        off = get_official_package(rfp, KIND_RFP)
        self.assertIsNotNone(off)

    def test_clear_devcode_also_clears_working_copy(self):
        consultant = models.User(
            email="c5@example.com",
            full_name="C5",
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
        get_working_package(self.db, rfp, KIND_RFP)
        self.db.commit()
        self.db.refresh(rfp)
        self.assertTrue(has_delivered_code_working_copy(rfp))

        ok, err = clear_delivered_code_deliverable(self.db, KIND_RFP, int(rfp.id))
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.db.refresh(rfp)
        self.assertFalse(has_delivered_code_working_copy(rfp))
        self.assertEqual((rfp.delivered_code_status or "").strip(), "none")


if __name__ == "__main__":
    unittest.main()
