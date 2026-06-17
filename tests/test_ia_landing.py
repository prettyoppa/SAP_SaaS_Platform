"""Tests for guest homepage (/) and /ia alias."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_guest_root_returns_landing():
    r = client.get("/")
    assert r.status_code == 200
    assert "ia-landing-hero" in r.text
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


def test_guest_detail_section_when_configured():
    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for key, val in (
            ("ia_guest_detail_enabled", "1"),
            ("ia_guest_detail_md_ko", "## 테스트\n\n상세 **본문**"),
            ("ia_guest_detail_md_en", "## Test\n\nDetail **body**"),
        ):
            row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
            if row:
                row.value = val
            else:
                db.add(models.SiteSettings(key=key, value=val))
        db.commit()
    finally:
        db.close()

    r = client.get("/")
    assert r.status_code == 200
    assert "ia-landing-detail" in r.text
    assert "테스트" in r.text or "Test" in r.text
