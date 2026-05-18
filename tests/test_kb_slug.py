"""KB slug helpers."""

import unittest
from unittest.mock import MagicMock

from app.kb_slug import ensure_unique_kb_slug, slugify_kb_title


class KbSlugTests(unittest.TestCase):
    def test_slugify_ascii_title(self) -> None:
        self.assertEqual(
            slugify_kb_title("BAPI Sales Order Tips"),
            "bapi-sales-order-tips",
        )

    def test_slugify_korean_fallback_hash(self) -> None:
        slug = slugify_kb_title("입고 처리 체크리스트")
        self.assertTrue(slug.startswith("kb-"))
        self.assertRegex(slug, r"^kb-[a-f0-9]{12}$")

    def test_slugify_mixed_keeps_ascii_tokens(self) -> None:
        slug = slugify_kb_title("SAP MM 입고 처리")
        self.assertIn("sap", slug)
        self.assertIn("mm", slug)

    def test_ensure_unique_appends_suffix(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [object(), None]
        out = ensure_unique_kb_slug(db, "my-article")
        self.assertEqual(out, "my-article-2")


if __name__ == "__main__":
    unittest.main()
