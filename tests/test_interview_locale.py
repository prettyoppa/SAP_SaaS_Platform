"""Interview question locale follows member preferred_lang."""

from app.interview_locale import (
    default_interview_questions,
    interview_lang_for_user,
    mia_interview_prompt_bundle,
    normalize_interview_lang,
    section6_fallback_suggestions,
)


class _User:
    def __init__(self, preferred_lang: str | None):
        self.preferred_lang = preferred_lang


def test_normalize_interview_lang():
    assert normalize_interview_lang("en") == "en"
    assert normalize_interview_lang("EN") == "en"
    assert normalize_interview_lang("ko") == "ko"
    assert normalize_interview_lang(None) == "ko"
    assert normalize_interview_lang("") == "ko"


def test_interview_lang_for_user():
    assert interview_lang_for_user(None) == "ko"
    assert interview_lang_for_user(_User("en")) == "en"
    assert interview_lang_for_user(_User("ko")) == "ko"


def test_default_questions_by_lang():
    ko = default_interview_questions("ko")
    en = default_interview_questions("en")
    assert ko and en
    assert ko != en
    assert "사용자" in ko[0]
    assert "user" in en[0].lower()


def test_mia_prompt_includes_output_language_en():
    bundle = mia_interview_prompt_bundle("en")
    assert "Output language" in bundle
    assert "English" in bundle


def test_mia_prompt_includes_output_language_ko():
    bundle = mia_interview_prompt_bundle("ko")
    assert "출력 언어" in bundle
    assert "한국어" in bundle


def test_section6_fallback_suggestions_en():
    su = section6_fallback_suggestions("en")
    assert su[0].startswith("Proceed")
