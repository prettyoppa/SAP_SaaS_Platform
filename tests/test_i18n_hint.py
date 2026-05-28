from starlette.requests import Request

from app.i18n_hint import initial_lang_from_request


def _req(headers=None, query=""):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": query.encode(),
    }
    return Request(scope)


def test_us_country_defaults_en_even_with_ko_secondary_accept():
    r = _req(
        headers={
            "CF-IPCountry": "US",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        }
    )
    assert initial_lang_from_request(r) == "en"


def test_kr_country_forces_ko():
    r = _req(headers={"CF-IPCountry": "KR", "Accept-Language": "en-US"})
    assert initial_lang_from_request(r) == "ko"


def test_query_lang_override():
    r = _req(headers={"CF-IPCountry": "US"}, query="lang=ko")
    assert initial_lang_from_request(r) == "ko"


def test_unknown_country_defaults_en():
    r = _req(headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
    assert initial_lang_from_request(r) == "en"
