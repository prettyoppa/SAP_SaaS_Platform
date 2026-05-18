"""KB slug 생성·유일성."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy.orm import Session

from . import models

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 180


def slugify_kb_title(raw: str, *, fallback: str = "kb") -> str:
    text = unicodedata.normalize("NFKC", (raw or "").strip())
    asciiish = text.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", asciiish).strip("-")
    if slug and re.search(r"[a-z0-9]", slug):
        return slug[:_MAX_SLUG_LEN].strip("-") or fallback
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{fallback}-{digest}"


def ensure_unique_kb_slug(db: Session, base_slug: str, *, exclude_id: int | None = None) -> str:
    root = (base_slug or "kb").strip("-")[:_MAX_SLUG_LEN] or "kb"
    candidate = root
    n = 2
    while True:
        q = db.query(models.KnowledgeArticle.id).filter(models.KnowledgeArticle.slug == candidate)
        if exclude_id is not None:
            q = q.filter(models.KnowledgeArticle.id != exclude_id)
        if q.first() is None:
            return candidate
        suffix = f"-{n}"
        candidate = f"{root[: _MAX_SLUG_LEN - len(suffix)]}{suffix}"
        n += 1
