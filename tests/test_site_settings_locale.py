from unittest.mock import MagicMock, patch

from app.site_settings_locale import enrich_site_settings, resolve_ko_en


def test_resolve_ko_en_uses_existing_en():
    db = MagicMock()
    ko, en = resolve_ko_en(
        db,
        {"home_hero_title": "안녕", "home_hero_title_en": "Hello"},
        "home_hero_title",
        "home_hero_title_en",
        purpose="test",
    )
    assert ko == "안녕"
    assert en == "Hello"


@patch("app.site_settings_locale.get_or_translate_ko_to_en", return_value="Translated")
def test_resolve_ko_en_translates_when_en_missing(mock_tr):
    db = MagicMock()
    ko, en = resolve_ko_en(
        db,
        {"home_hero_title": "제목"},
        "home_hero_title",
        "home_hero_title_en",
        purpose="test",
    )
    assert ko == "제목"
    assert en == "Translated"
    mock_tr.assert_called_once()


@patch("app.site_settings_locale.get_or_translate_ko_to_en")
def test_enrich_skips_when_en_present(mock_tr):
    db = MagicMock()
    out = enrich_site_settings(
        db,
        {"home_tile_abap_title_ko": "신규", "home_tile_abap_title_en": "New"},
        scope="home",
    )
    assert out["home_tile_abap_title_en"] == "New"
    mock_tr.assert_not_called()
