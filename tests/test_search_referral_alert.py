"""검색 유입 분류·알림."""

from unittest.mock import MagicMock, patch

from app.search_referral_alert import (
    classify_search_referrer,
    search_referral_alerts_enabled,
    _process_search_referral,
    _rate_limit_ok,
    _should_inspect_request,
)


def test_direct_access_no_referer():
    assert classify_search_referrer(None, site_host="sap.ireadschool.com") is None
    assert classify_search_referrer("", site_host="sap.ireadschool.com") is None


def test_google_referer():
    assert (
        classify_search_referrer(
            "https://www.google.com/search?q=sap+dev+hub",
            site_host="sap.ireadschool.com",
        )
        == "Google"
    )


def test_naver_referer():
    assert (
        classify_search_referrer(
            "https://search.naver.com/search.naver?query=test",
            site_host="sap.ireadschool.com",
        )
        == "Naver"
    )


def test_same_site_referer_ignored():
    assert (
        classify_search_referrer(
            "https://sap.ireadschool.com/kb/foo",
            site_host="sap.ireadschool.com",
        )
        is None
    )


def test_non_search_external_ignored():
    assert (
        classify_search_referrer(
            "https://example.com/link",
            site_host="sap.ireadschool.com",
        )
        is None
    )


def test_should_inspect_html_paths():
    assert _should_inspect_request("GET", "/") is True
    assert _should_inspect_request("GET", "/kb/my-article") is True
    assert _should_inspect_request("GET", "/static/js/main.js") is False
    assert _should_inspect_request("POST", "/") is False


def test_rate_limit_dedupes():
    assert _rate_limit_ok("1.2.3.4", "Google") is True
    assert _rate_limit_ok("1.2.3.4", "Google") is False
    assert _rate_limit_ok("1.2.3.4", "Naver") is True


@patch("app.search_referral_alert.sms_enabled", return_value=True)
@patch("app.search_referral_alert.search_referral_alerts_enabled", return_value=True)
@patch("app.search_referral_alert._notify_admins_search_referral")
def test_process_sends_for_google(mock_notify, _en, _sms):
    _process_search_referral(
        referer="https://www.google.com/search?q=x",
        site_host="sap.ireadschool.com",
        path="/kb/test",
        client_ip="9.9.9.9",
        user_agent="Mozilla/5.0",
        skip_admin_session=False,
    )
    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][1] == "Google"
