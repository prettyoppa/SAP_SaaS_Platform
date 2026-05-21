"""초안 본문 ↔ SiteSettings 동기화 · 이용 안내 마크다운 조회.

배포 이미지: app/data/content_drafts/ (Docker COPY app 에 포함)
로컬 개발: docs/legal, docs/user_guide 가 있으면 우선 사용
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from . import models

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLE_DIR = Path(__file__).resolve().parent / "data" / "content_drafts"

LEGAL_KEYS = ("terms_of_service", "privacy_policy")
LEGAL_FILENAMES = {
    "terms_of_service": "terms_of_service_ko.txt",
    "privacy_policy": "privacy_policy_ko.txt",
}

USER_GUIDE_SETTING_KO = "user_guide_markdown_ko"
USER_GUIDE_SETTING_EN = "user_guide_markdown_en"
USER_GUIDE_FILENAMES = {"ko": "user_guide_ko.txt", "en": "user_guide_en.txt"}

CONTENT_DRAFTS_HASH_KEY = "content_drafts_file_hash"

_MIN_LEGAL_LEN = 400


def _pick_existing(*candidates: Path) -> Path | None:
    for p in candidates:
        if p.is_file():
            return p
    return None


def legal_file_path(key: str) -> Path | None:
    fn = LEGAL_FILENAMES.get(key)
    if not fn:
        return None
    return _pick_existing(
        _REPO_ROOT / "docs" / "legal" / fn,
        _BUNDLE_DIR / fn,
    )


def user_guide_file_path(lang: str = "ko") -> Path | None:
    fn = USER_GUIDE_FILENAMES.get(lang, USER_GUIDE_FILENAMES["ko"])
    sub = "user_guide"
    return _pick_existing(
        _REPO_ROOT / "docs" / sub / f"user_guide_{lang}.md",
        _BUNDLE_DIR / fn,
    )


def _draft_paths() -> list[Path]:
    out: list[Path] = []
    for key in LEGAL_KEYS:
        p = legal_file_path(key)
        if p:
            out.append(p)
    for lang in ("ko", "en"):
        p = user_guide_file_path(lang)
        if p:
            out.append(p)
    return out


def _sha256_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.as_posix()):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


def _read_text(path: Path) -> str:
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
    for key in LEGAL_KEYS:
        if _setting_len(db, key) < _MIN_LEGAL_LEN:
            return True
    if _setting_len(db, USER_GUIDE_SETTING_KO) < 200:
        return True
    paths = _draft_paths()
    if not paths:
        return False
    flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == CONTENT_DRAFTS_HASH_KEY).first()
    stored = (flag.value or "").strip() if flag else ""
    return stored != _sha256_files(paths)


def sync_content_drafts_from_files(db: Session, *, force: bool = False) -> bool:
    """
    초안 파일 → SiteSettings. 파일이 없으면 False(예외 없음).
    """
    paths = _draft_paths()
    if not paths:
        _log.warning("[content_drafts] no draft files found under bundle or docs/")
        return False

    file_hash = _sha256_files(paths)
    if not force and not content_drafts_need_sync(db):
        return False

    updated = False
    for key in LEGAL_KEYS:
        path = legal_file_path(key)
        if not path:
            _log.warning("[content_drafts] missing legal file for %s", key)
            continue
        _upsert(db, key, _read_text(path))
        updated = True

    for lang, setting_key in (("ko", USER_GUIDE_SETTING_KO), ("en", USER_GUIDE_SETTING_EN)):
        path = user_guide_file_path(lang)
        if not path:
            continue
        _upsert(db, setting_key, _read_text(path))
        updated = True

    if updated:
        _upsert(db, CONTENT_DRAFTS_HASH_KEY, file_hash)
        db.commit()
    return updated


def get_user_guide_markdown(db: Session, *, lang: str = "ko") -> str:
    """DB → 파일 순으로 이용 안내 마크다운."""
    setting_key = USER_GUIDE_SETTING_EN if lang == "en" else USER_GUIDE_SETTING_KO
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == setting_key).first()
    if row and (row.value or "").strip():
        return row.value.strip()
    path = user_guide_file_path(lang)
    if path:
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
