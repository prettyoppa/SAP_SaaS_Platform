"""docs/ 초안 파일 ↔ SiteSettings 동기화 · 이용 안내 마크다운 조회."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy.orm import Session

from . import models

_REPO_ROOT = Path(__file__).resolve().parent.parent

LEGAL_FILES: dict[str, Path] = {
    "terms_of_service": _REPO_ROOT / "docs" / "legal" / "terms_of_service_ko.txt",
    "privacy_policy": _REPO_ROOT / "docs" / "legal" / "privacy_policy_ko.txt",
}

USER_GUIDE_KO_PATH = _REPO_ROOT / "docs" / "user_guide" / "user_guide_ko.md"
USER_GUIDE_EN_PATH = _REPO_ROOT / "docs" / "user_guide" / "user_guide_en.md"

USER_GUIDE_SETTING_KO = "user_guide_markdown_ko"
USER_GUIDE_SETTING_EN = "user_guide_markdown_en"
CONTENT_DRAFTS_HASH_KEY = "content_drafts_file_hash"

# DB 값이 이보다 짧으면 «비어 있음»으로 보고 파일에서 다시 채움
_MIN_LEGAL_LEN = 400


def _sha256_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        if p.is_file():
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def _draft_paths() -> list[Path]:
    paths = list(LEGAL_FILES.values())
    if USER_GUIDE_KO_PATH.is_file():
        paths.append(USER_GUIDE_KO_PATH)
    if USER_GUIDE_EN_PATH.is_file():
        paths.append(USER_GUIDE_EN_PATH)
    return paths


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Draft file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _upsert(db: Session, key: str, value: str) -> None:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.SiteSettings(key=key, value=value))


def _setting_len(db: Session, key: str) -> int:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    return len((row.value or "").strip()) if row else 0


def content_drafts_need_sync(db: Session) -> bool:
    for key in LEGAL_FILES:
        if _setting_len(db, key) < _MIN_LEGAL_LEN:
            return True
    if _setting_len(db, USER_GUIDE_SETTING_KO) < 200:
        return True
    flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == CONTENT_DRAFTS_HASH_KEY).first()
    stored = (flag.value or "").strip() if flag else ""
    try:
        current = _sha256_files(_draft_paths())
    except FileNotFoundError:
        return False
    return stored != current


def sync_content_drafts_from_files(db: Session, *, force: bool = False) -> bool:
    """
    docs/legal, docs/user_guide → SiteSettings.
    force=True 이면 해시와 관계없이 덮어씀(관리자 «초안 다시 불러오기»).
    """
    paths = _draft_paths()
    if not paths:
        return False

    try:
        file_hash = _sha256_files(paths)
    except FileNotFoundError:
        return False

    if not force and not content_drafts_need_sync(db):
        return False

    for key, path in LEGAL_FILES.items():
        _upsert(db, key, _read_text(path))

    if USER_GUIDE_KO_PATH.is_file():
        _upsert(db, USER_GUIDE_SETTING_KO, _read_text(USER_GUIDE_KO_PATH))
    if USER_GUIDE_EN_PATH.is_file():
        _upsert(db, USER_GUIDE_SETTING_EN, _read_text(USER_GUIDE_EN_PATH))

    _upsert(db, CONTENT_DRAFTS_HASH_KEY, file_hash)
    db.commit()
    return True


def get_user_guide_markdown(db: Session, *, lang: str = "ko") -> str:
    """DB → 파일 순으로 이용 안내 마크다운."""
    key = USER_GUIDE_SETTING_EN if lang == "en" else USER_GUIDE_SETTING_KO
    path = USER_GUIDE_EN_PATH if lang == "en" else USER_GUIDE_KO_PATH
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    if row and (row.value or "").strip():
        return row.value.strip()
    if path.is_file():
        return _read_text(path)
    return ""


def markdown_to_plain_document(md: str) -> str:
    """PDF·프린트용: 마크다운을 줄 단위 평문으로(구조 유지)."""
    out: list[str] = []
    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if not line:
            out.append("")
            continue
        if line.startswith("# ") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            out.append("")
            out.append(line[3:].strip())
            out.append("")
            continue
        if line.startswith("### "):
            out.append(line[4:].strip())
            continue
        s = line
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        if s.startswith("|") and s.endswith("|"):
            s = re.sub(r"\|", " ", s).strip()
        if s.strip() in ("---", "***"):
            continue
        out.append(s)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)
