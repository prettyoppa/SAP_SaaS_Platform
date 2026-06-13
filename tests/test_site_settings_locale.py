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
def test_resolve_ko_en_translates_when_admin_auto_translate(mock_tr):
    db = MagicMock()
    ko, en = resolve_ko_en(
        db,
        {"home_hero_title": "제목"},
        "home_hero_title",
        "home_hero_title_en",
        purpose="test",
        auto_translate=True,
    )
    assert ko == "제목"
    assert en == "Translated"
    mock_tr.assert_called_once()


@patch("app.site_settings_locale.get_or_translate_ko_to_en")
@patch("app.site_settings_locale.read_cached_translation", return_value="")
def test_resolve_ko_en_falls_back_to_ko_on_page_load(mock_cache, mock_tr):
    db = MagicMock()
    ko, en = resolve_ko_en(
        db,
        {"home_hero_title": "제목"},
        "home_hero_title",
        "home_hero_title_en",
        purpose="test",
    )
    assert en == "제목"
    mock_tr.assert_not_called()


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


@patch("app.site_settings_locale.get_or_translate_ko_to_en")
@patch("app.site_settings_locale.read_cached_translation", return_value="Cached EN")
def test_enrich_uses_cache_without_gemini(mock_cache, mock_tr):
    db = MagicMock()
    out = enrich_site_settings(
        db,
        {"home_tile_abap_title_ko": "신규"},
        scope="home",
    )
    assert out["home_tile_abap_title_en"] == "Cached EN"
    mock_tr.assert_not_called()
    assert any(c.kwargs.get("namespace") == "home_tile_abap_title_en" for c in mock_cache.call_args_list)


@patch("app.site_settings_locale.get_or_translate_ko_to_en")
@patch("app.site_settings_locale.read_cached_translation", return_value="")
def test_enrich_ko_fallback_when_no_cache(mock_cache, mock_tr):
    db = MagicMock()
    out = enrich_site_settings(
        db,
        {"service_abap_intro_md_ko": "소개"},
        scope="service",
    )
    assert out["service_abap_intro_md_en"] == "소개"
    mock_tr.assert_not_called()
