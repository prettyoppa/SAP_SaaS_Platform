"""Profile edit form — language/currency defaults from DB."""

from types import SimpleNamespace

from app.routers.auth_router import (
    _profile_lang_currency_from_form,
    _profile_lang_currency_from_user,
)


def test_profile_lang_currency_from_user():
    user = SimpleNamespace(preferred_lang="en", billing_currency="USD")
    assert _profile_lang_currency_from_user(user) == ("en", "USD")


def test_profile_lang_currency_from_form_uses_submitted():
    user = SimpleNamespace(preferred_lang="en", billing_currency="USD")
    assert _profile_lang_currency_from_form(user, "ko", "KRW") == ("ko", "KRW")


def test_profile_lang_currency_from_form_falls_back_to_user():
    user = SimpleNamespace(preferred_lang="en", billing_currency="USD")
    assert _profile_lang_currency_from_form(user, "", "") == ("en", "USD")
