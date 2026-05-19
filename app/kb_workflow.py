"""SAP 지식갤러리(KB) 검수·발행 워크플로."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from . import models

STATUS_DRAFT = "draft"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"

KB_WORKFLOW_STATUSES = (
    STATUS_DRAFT,
    STATUS_PENDING_REVIEW,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
)

STATUS_LABEL_KO: dict[str, str] = {
    STATUS_DRAFT: "초안",
    STATUS_PENDING_REVIEW: "검수 대기",
    STATUS_PUBLISHED: "발행",
    STATUS_REJECTED: "반려",
}

STATUS_LABEL_EN: dict[str, str] = {
    STATUS_DRAFT: "Draft",
    STATUS_PENDING_REVIEW: "Pending review",
    STATUS_PUBLISHED: "Published",
    STATUS_REJECTED: "Rejected",
}


def normalize_workflow_status(raw: str | None) -> str:
    s = (raw or STATUS_DRAFT).strip().lower()
    return s if s in KB_WORKFLOW_STATUSES else STATUS_DRAFT


def sync_publish_flags(article: models.KnowledgeArticle) -> None:
    """workflow_status ↔ is_published 일관성."""
    st = normalize_workflow_status(getattr(article, "workflow_status", None))
    article.workflow_status = st
    if st == STATUS_PUBLISHED:
        article.is_published = True
        if not article.published_at:
            article.published_at = datetime.utcnow()
    else:
        article.is_published = False


def approve_article(article: models.KnowledgeArticle) -> None:
    article.workflow_status = STATUS_PUBLISHED
    article.is_published = True
    if not article.published_at:
        article.published_at = datetime.utcnow()
    article.reviewed_at = datetime.utcnow()


def reject_article(article: models.KnowledgeArticle) -> None:
    article.workflow_status = STATUS_REJECTED
    article.is_published = False
    article.reviewed_at = datetime.utcnow()


def submit_for_review(article: models.KnowledgeArticle) -> None:
    article.workflow_status = STATUS_PENDING_REVIEW
    article.is_published = False


def is_publicly_visible(article: models.KnowledgeArticle, *, now: datetime | None = None) -> bool:
    if not article.is_published:
        return False
    st = normalize_workflow_status(getattr(article, "workflow_status", None))
    if st != STATUS_PUBLISHED:
        return False
    pub = article.published_at
    if pub is None:
        return True
    ref = now or datetime.utcnow()
    return pub <= ref


def migrate_legacy_workflow_statuses(db: Session) -> None:
    """기존 행: is_published → published, 그 외 draft."""
    rows = db.query(models.KnowledgeArticle).all()
    changed = False
    for a in rows:
        cur = (getattr(a, "workflow_status", None) or "").strip()
        if cur in KB_WORKFLOW_STATUSES:
            continue
        a.workflow_status = STATUS_PUBLISHED if a.is_published else STATUS_DRAFT
        changed = True
    if changed:
        db.commit()
