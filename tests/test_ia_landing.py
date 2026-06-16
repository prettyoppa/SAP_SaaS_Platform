"""Tests for /ia landing (non-production home prototype)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ia_landing_returns_200_for_guest():
    r = client.get("/ia")
    assert r.status_code == 200
    assert "Catchy Lab" in r.text
    assert "구글 로그인" in r.text or "Google" in r.text
    assert "회원 가입" in r.text or "Sign up" in r.text


def test_ia_meta():
    r = client.get("/ia/_meta")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ia_landing") is True
    assert "/ia" in data.get("routes", [])
