"""Tests for guest homepage (/) and /ia alias."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_guest_root_returns_landing():
    r = client.get("/")
    assert r.status_code == 200
    assert "ia-landing-hero" in r.text
    assert "ia-guest-guide" in r.text
    assert "ia-guide-step-rows" in r.text
    assert "ia-guide-section-band" in r.text
    assert "ia-guide-section-divider" in r.text
    assert "ia-guide-card__intro" in r.text
    assert "markdown-body-lite" in r.text
    assert 'id="faq"' not in r.text
    assert "ia-landing-detail" not in r.text
    assert "Catchy Lab" in r.text
    assert "무료로 시작하기" in r.text or "Start free" in r.text
    assert "fab-action--start" not in r.text
    assert "noindex" not in r.text.lower()
    assert 'rel="canonical"' in r.text


def test_ia_redirects_to_root_for_guest():
    r = client.get("/ia", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert r.headers.get("location") == "/"


def test_ia_meta():
    r = client.get("/ia/_meta")
    assert r.status_code == 200
    data = r.json()
    assert data.get("guest_home") is True
    assert "/" in data.get("routes", [])
