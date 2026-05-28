"""Markdown 초안 ↔ SiteSettings · 공개 문서 조회.

배포: app/data/content_drafts/*.md (Docker COPY app)
로컬: docs/legal, docs/user_guide 우선
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from . import models

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLE_DIR = Path(__file__).resolve().parent / "data" / "content_drafts"

DocKind = Literal["terms", "privacy", "user_guide"]

_DOC_SPECS: dict[DocKind, dict[str, str]] = {
    "terms": {
        "basename": "terms_of_service",
        "setting_ko": "terms_markdown_ko",
        "setting_en": "terms_markdown_en",
        "pdf": "/static/docs/terms-of-service.pdf",
        "docs_subdir": "legal",
    },
    "privacy": {
        "basename": "privacy_policy",
        "setting_ko": "privacy_markdown_ko",
        "setting_en": "privacy_markdown_en",
        "pdf": "/static/docs/privacy-policy.pdf",
        "docs_subdir": "legal",
    },
    "user_guide": {
        "basename": "user_guide",
        "setting_ko": "user_guide_markdown_ko",
        "setting_en": "user_guide_markdown_en",
        "pdf": "/static/docs/user-guide.pdf",
        "docs_subdir": "user_guide",
    },
}

CONTENT_DRAFTS_HASH_KEY = "content_drafts_file_hash_v2"
_MIN_MARKDOWN_LEN = 200


def _pick_existing(*candidates: Path) -> Path | None:
    for p in candidates:
        if p.is_file():
            return p
    return None


def markdown_file_path(kind: DocKind, lang: str = "ko") -> Path | None:
    spec = _DOC_SPECS[kind]
    base = spec["basename"]
    sub = spec["docs_subdir"]
    name = f"{base}_{lang}.md"
    return _pick_existing(
        _REPO_ROOT / "docs" / sub / name,
        _BUNDLE_DIR / name,
    )


def pdf_url_for(kind: DocKind, *, cache_suffix: str = "20260521") -> str:
    url = _DOC_SPECS[kind]["pdf"]
    if url.endswith(".pdf"):
        return f"{url}?v={cache_suffix}"
    return url


def _draft_paths() -> list[Path]:
    out: list[Path] = []
    for kind in _DOC_SPECS:
        for lang in ("ko", "en"):
            p = markdown_file_path(kind, lang)
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
    for spec in _DOC_SPECS.values():
        if _setting_len(db, spec["setting_ko"]) < _MIN_MARKDOWN_LEN:
            return True
    paths = _draft_paths()
    if not paths:
        return False
    flag = db.query(models.SiteSettings).filter(models.SiteSettings.key == CONTENT_DRAFTS_HASH_KEY).first()
    stored = (flag.value or "").strip() if flag else ""
    return stored != _sha256_files(paths)


def sync_content_drafts_from_files(db: Session, *, force: bool = False) -> bool:
    paths = _draft_paths()
    if not paths:
        _log.warning("[content_drafts] no markdown draft files found")
        return False

    file_hash = _sha256_files(paths)
    if not force and not content_drafts_need_sync(db):
        return False

    updated = False
    for kind, spec in _DOC_SPECS.items():
        for lang, key in (("ko", spec["setting_ko"]), ("en", spec["setting_en"])):
            path = markdown_file_path(kind, lang)
            if not path:
                continue
            _upsert(db, key, _read_text(path))
            updated = True

    if updated:
        _upsert(db, CONTENT_DRAFTS_HASH_KEY, file_hash)
        db.commit()
    return updated


def get_document_markdown(db: Session, kind: DocKind, *, lang: str = "ko") -> str:
    spec = _DOC_SPECS[kind]
    setting_ko = spec["setting_ko"]
    setting_en = spec["setting_en"]
    row_ko = db.query(models.SiteSettings).filter(models.SiteSettings.key == setting_ko).first()
    md_ko = (row_ko.value or "").strip() if row_ko else ""
    if not md_ko:
        path_ko = markdown_file_path(kind, "ko")
        if path_ko:
            md_ko = _read_text(path_ko).strip()
    if lang == "ko":
        return md_ko
    row_en = db.query(models.SiteSettings).filter(models.SiteSettings.key == setting_en).first()
    md_en = (row_en.value or "").strip() if row_en else ""
    if not md_en:
        path_en = markdown_file_path(kind, "en")
        if path_en:
            md_en = _read_text(path_en).strip()
    if md_en:
        return md_en
    if not md_ko:
        return ""
    from .site_settings_locale import effective_en

    purpose = {"terms": "Terms of service", "privacy": "Privacy policy", "user_guide": "User guide"}.get(
        kind, kind
    )
    settings = {setting_ko: md_ko, setting_en: ""}
    return effective_en(db, settings, setting_ko, setting_en, purpose=purpose)


def get_user_guide_markdown(db: Session, *, lang: str = "ko") -> str:
    return get_document_markdown(db, "user_guide", lang=lang)


def has_document(db: Session, kind: DocKind, *, lang: str = "ko") -> bool:
    return bool(get_document_markdown(db, kind, lang=lang).strip())


def markdown_to_plain_document(md: str) -> str:
    """PDF용 평문(줄 구조 유지)."""
    out: list[str] = []
    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if not line:
            out.append("")
            continue
        if line.startswith("# "):
            out.append("")
            out.append(line[2:].strip())
            out.append("")
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
