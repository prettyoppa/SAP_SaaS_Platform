"""Service landing intro HTML from SiteSettings."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.service_landing_intro import service_landing_intro_context


class ServiceLandingIntroTests(unittest.TestCase):
    @patch("app.service_landing_intro.enrich_site_settings")
    @patch("app.service_landing_intro.load_service_integration_settings_dict", return_value={})
    @patch("app.service_landing_intro.load_service_analysis_settings_dict", return_value={})
    @patch("app.service_landing_intro.load_service_abap_settings_dict")
    @patch("app.service_landing_intro.markdown_to_html", side_effect=lambda md: f"<p>{md}</p>")
    def test_uses_site_settings_markdown(
        self,
        _html,
        mock_abap,
        _analysis,
        _integration,
        mock_enrich,
    ):
        mock_abap.return_value = {"service_abap_intro_md_ko": "관리자 설정 소개"}
        mock_enrich.side_effect = lambda _db, settings, **_: settings
        db = MagicMock()
        ctx = service_landing_intro_context(db)
        self.assertIn("관리자 설정 소개", ctx["service_abap_intro_html_ko"])


if __name__ == "__main__":
    unittest.main()
