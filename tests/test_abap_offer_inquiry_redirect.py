from app.routers.abap_analysis_router import _abap_proposal_hub_redirect, _append_query_to_hub_path


def test_abap_proposal_hub_redirect_puts_query_before_fragment():
    url = _abap_proposal_hub_redirect(6, offer_inquiry_ok="1")
    assert url == "/abap-analysis/6?offer_inquiry_ok=1#abap-phase-proposal"


def test_abap_proposal_hub_redirect_console_readonly():
    url = _abap_proposal_hub_redirect(6, console_readonly=True, offer_inquiry_err="fail")
    assert url == "/abap-analysis/6/console-readonly?offer_inquiry_err=fail#abap-phase-proposal"


def test_append_query_to_hub_path():
    assert (
        _append_query_to_hub_path("/abap-analysis/6/console-readonly?phase=proposal", offer_inquiry_ok="1")
        == "/abap-analysis/6/console-readonly?phase=proposal&offer_inquiry_ok=1"
    )
