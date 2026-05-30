"""kb_request_flow helpers."""

import unittest

from app.kb_request_flow import (
    _parse_source_note,
    _payload_passes_codelib_guard,
    _redact_code_fences,
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

    def test_redact_code_fences(self):
        raw = "intro\n```abap\nWRITE hello.\n```\noutro"
        out = _redact_code_fences(raw)
        self.assertNotIn("WRITE hello", out)
        self.assertIn("공개 KB", out)

    def test_codelib_guard_blocks_markers(self):
        self.assertFalse(
            _payload_passes_codelib_guard(
                {
                    "title": "SAP ALV",
                    "excerpt": "x",
                    "meta_description": "x",
                    "body_md": "코드갤러리 예제 참고",
                    "tags": "alv",
                }
            )
        )
        self.assertTrue(
            _payload_passes_codelib_guard(
                {
                    "title": "SAP ALV 패턴",
                    "excerpt": "x",
                    "meta_description": "x",
                    "body_md": "ALV 필드카탈로그 설정 요약",
                    "tags": "alv",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
