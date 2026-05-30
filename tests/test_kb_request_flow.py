"""kb_request_flow helpers."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.kb_request_flow import (
    _parse_source_note,
    _stages_done,
    flow_key,
    request_flow_enabled,
)


class KbRequestFlowTests(unittest.TestCase):
    def test_flow_key(self):
        self.assertEqual(flow_key("rfp", 42), "rfp:42")
        self.assertEqual(flow_key(" integration ", 7), "integration:7")

    def test_stages_done_parsing(self):
        note = _parse_source_note('{"stages": ["proposal", "delivery"]}')
        self.assertEqual(_stages_done(note), {"proposal", "delivery"})

    def test_request_flow_enabled_default_on(self):
        import os

        prev = os.environ.get("KB_REQUEST_FLOW_ENABLED")
        try:
            os.environ.pop("KB_REQUEST_FLOW_ENABLED", None)
            self.assertTrue(request_flow_enabled())
            os.environ["KB_REQUEST_FLOW_ENABLED"] = "0"
            self.assertFalse(request_flow_enabled())
        finally:
            if prev is None:
                os.environ.pop("KB_REQUEST_FLOW_ENABLED", None)
            else:
                os.environ["KB_REQUEST_FLOW_ENABLED"] = prev

    def test_owner_is_test_skips_llm(self):
        from app import kb_request_flow

        with patch.object(kb_request_flow, "_generate_article_fields", return_value=None) as mock_gen:
            db = MagicMock()
            owner = SimpleNamespace(is_test_account=True)
            rfp = SimpleNamespace(
                id=1,
                user_id=9,
                title="비밀 프로젝트",
                sap_modules="MM",
                dev_types="report",
                proposal_text="x",
                fs_text="",
                delivered_code_status="none",
            )
            db.query.return_value.filter.return_value.first.side_effect = [rfp, owner]
            with patch("app.database.SessionLocal", lambda: db):
                kb_request_flow.run_request_kb_flow("rfp", 1, "proposal")
            mock_gen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
