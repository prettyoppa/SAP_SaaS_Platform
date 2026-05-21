"""이용약관·개인정보 — docs/legal → SiteSettings (content_drafts 위임)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .content_drafts import sync_content_drafts_from_files


def seed_legal_site_content(db: Session) -> bool:
    return sync_content_drafts_from_files(db, force=False)
