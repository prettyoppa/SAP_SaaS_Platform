"""홈 히어로 제목·서브카피·부제 필드."""

import unittest

from app.home_hero_defaults import (
    hero_title_to_markup,
    normalize_hero_title_storage,
    resolve_home_hero_fields,
)


class HomeHeroFieldsTests(unittest.TestCase):
    def test_title_br_max_three_lines(self) -> None:
        stored = normalize_hero_title_storage("A<br>B<br>C")
        self.assertEqual(stored, "A<br>B<br>C")
        markup = str(hero_title_to_markup(stored))
        self.assertIn("A", markup)
        self.assertIn("B", markup)
        self.assertIn("C", markup)

    def test_title_br_truncates_fourth_line(self) -> None:
        stored = normalize_hero_title_storage("A<br>B<br>C<br>D")
        self.assertEqual(stored, "A<br>B<br>C")
        markup = str(hero_title_to_markup(stored))
        self.assertNotIn("D", markup)

    def test_title_three_line_markup_blocks(self) -> None:
        raw = "SAP 개발,<br>Catch Lab의 전문가그룹과 함께<br>저비용 · 고효율을 경험해보세요."
        markup = str(hero_title_to_markup(raw))
        self.assertEqual(markup.count("hero-title-line"), 3)
        self.assertIn("함께", markup)
        self.assertIn("저비용", markup)

    def test_title_newline(self) -> None:
        stored = normalize_hero_title_storage("SAP 개발,\nCatchy가 함께 하겠습니다.")
        self.assertEqual(stored, "SAP 개발,<br>Catchy가 함께 하겠습니다.")

    def test_resolve_defaults(self) -> None:
        fields = resolve_home_hero_fields({})
        self.assertIn("SAP 개발", str(fields["title_markup"]))
        self.assertIn("with 8 Power Agents", fields["subcopy"])
        self.assertIn("AI 에이전트", fields["desc"])


if __name__ == "__main__":
    unittest.main()
