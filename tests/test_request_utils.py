"""request_utils helpers."""

from app.request_utils import is_https_request


def test_is_https_request_from_forwarded_proto() -> None:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-proto", b"https")],
        "query_string": b"",
    }
    assert is_https_request(Request(scope)) is True


def test_is_https_request_from_public_base_url() -> None:
    import os
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("example.com", 80),
    }
    req = Request(scope)
    old = os.environ.get("PUBLIC_BASE_URL")
    try:
        os.environ["PUBLIC_BASE_URL"] = "https://sap.ireadschool.com"
        assert is_https_request(req) is True
    finally:
        if old is None:
            os.environ.pop("PUBLIC_BASE_URL", None)
        else:
            os.environ["PUBLIC_BASE_URL"] = old
