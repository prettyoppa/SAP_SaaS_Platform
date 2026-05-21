"""이용약관·개인정보처리방침 — docs/legal 초안 → SiteSettings 동기화."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from . import models

# 초안 본문 변경 시 이 값을 올리면 기동 시 DB에 다시 반영됩니다.
LEGAL_CONTENT_REVISION = "20260520-draft-v1"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LEGAL_DIR = _REPO_ROOT / "docs" / "legal"

_KEY_FILES: dict[str, Path] = {
    "terms_of_service": _LEGAL_DIR / "terms_of_service_ko.txt",
    "privacy_policy": _LEGAL_DIR / "privacy_policy_ko.txt",
}


def _read_legal_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Legal draft missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _upsert_setting(db: Session, key: str, value: str) -> None:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.SiteSettings(key=key, value=value))


def seed_legal_site_content(db: Session) -> bool:
    """
    revision 플래그가 다르면 docs/legal KO 초안을 terms_of_service·privacy_policy에 반영.
    Returns True if content was updated.
    """
    flag_key = "legal_content_revision"
    flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == flag_key).first()
    current = (flag.value or "").strip() if flag else ""
    if current == LEGAL_CONTENT_REVISION:
        return False

    for key, path in _KEY_FILES.items():
        _upsert_setting(db, key, _read_legal_file(path))
    _upsert_setting(db, flag_key, LEGAL_CONTENT_REVISION)
    db.commit()
    return True
