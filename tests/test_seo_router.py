"""SEO robots.txt · sitemap.xml · llms.txt."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.llms_txt import build_llms_txt
from app.routers.seo_router import _build_sitemap_entries, _sitemap_url_block
from app.seo_indexing import (
    faq_has_indexable_answer,
    kb_has_indexable_body_ko,
    notice_has_indexable_body,
)


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
        self.assertNotIn("/abap-analysis", body)

    def test_sitemap_omits_empty_faq_and_app_hubs(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [
            [],  # notices
            [],  # faqs
            [],  # kb articles
        ]
        xml = "\n".join(_build_sitemap_entries("https://sap.example.com", db))
        self.assertIn("/about", xml)
        self.assertIn("/services/abap", xml)
        self.assertNotIn("/faqs", xml)
        self.assertNotIn("/notices", xml)
        self.assertNotIn("/abap-analysis", xml)
        self.assertNotIn("/integration", xml)

    def test_notice_indexable_requires_body(self) -> None:
        short = SimpleNamespace(content="짧음", content_en="")
        long = SimpleNamespace(content="x" * 100, content_en="")
        self.assertFalse(notice_has_indexable_body(short))
        self.assertTrue(notice_has_indexable_body(long))

    def test_faq_indexable_requires_answer(self) -> None:
        empty = SimpleNamespace(answer="", answer_en="")
        ok = SimpleNamespace(answer="x" * 50, answer_en="")
        self.assertFalse(faq_has_indexable_answer(empty))
        self.assertTrue(faq_has_indexable_answer(ok))

    def test_kb_indexable_requires_body(self) -> None:
        thin = SimpleNamespace(slug="sap-test", body_md="short")
        rich = SimpleNamespace(slug="sap-test", body_md="x" * 250)
        self.assertFalse(kb_has_indexable_body_ko(thin))
        self.assertTrue(kb_has_indexable_body_ko(rich))


if __name__ == "__main__":
    unittest.main()
