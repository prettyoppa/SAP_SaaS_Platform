"""SEO robots.txt · sitemap.xml · llms.txt."""

import unittest

from app.llms_txt import build_llms_txt
from app.routers.seo_router import _sitemap_url_block


class SeoRouterTests(unittest.TestCase):
    def test_sitemap_url_escapes_ampersand(self) -> None:
        block = _sitemap_url_block(
            "https://example.com/faqs?x=1&amp;y=2",
            "2026-05-16",
            "monthly",
            "0.6",
        )
        self.assertIn("&amp;", block)
        self.assertNotIn("?x=1&y=2", block)

    def test_llms_txt_mentions_sap_and_about(self) -> None:
        body = build_llms_txt("https://sap.example.com")
        self.assertIn("SAP Development Partner", body)
        self.assertIn("/about", body)
        self.assertIn("NOT affiliated with SAP SE", body)


if __name__ == "__main__":
    unittest.main()
