"""SEO robots.txt · sitemap.xml."""

import unittest
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
