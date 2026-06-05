"""관리자 지식갤러리 목록 — 작성자·작성 시각 표시용."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import models
from .kb_request_flow import SOURCE_KIND, _parse_source_note


@dataclass
class KbAdminListRow:
    article: models.KnowledgeArticle
    author_email: str | None


def _owner_user_id_for_request(db: Session, request_kind: str, request_id: int) -> int | None:
    kind = (request_kind or "").strip().lower()
    rid = int(request_id)
    if kind == "rfp":
        uid = db.query(models.RFP.user_id).filter(models.RFP.id == rid).scalar()
    elif kind == "analysis":
        uid = (
            db.query(models.AbapAnalysisRequest.user_id)
            .filter(models.AbapAnalysisRequest.id == rid)
            .scalar()
        )
    elif kind == "integration":
        uid = (
            db.query(models.IntegrationRequest.user_id)
            .filter(models.IntegrationRequest.id == rid)
            .scalar()
        )
    else:
        return None
    return int(uid) if uid is not None else None


def _resolve_author_user_ids(
    db: Session,
    articles: list[models.KnowledgeArticle],
) -> dict[int, int | None]:
    """article.id → author user_id (없으면 None)."""
    out: dict[int, int | None] = {}
    for article in articles:
        uid = getattr(article, "author_user_id", None)
        if uid:
            out[article.id] = int(uid)
            continue
        if (article.source_kind or "").strip() != SOURCE_KIND:
            out[article.id] = None
            continue
        note = _parse_source_note(article.source_note)
        kind = (note.get("request_kind") or "").strip().lower()
        rid_raw = note.get("request_id")
        try:
            rid = int(rid_raw)
        except (TypeError, ValueError):
            out[article.id] = None
            continue
        out[article.id] = _owner_user_id_for_request(db, kind, rid)
    return out


def kb_admin_list_rows(db: Session, articles: list[models.KnowledgeArticle]) -> list[KbAdminListRow]:
    if not articles:
        return []
    author_ids = _resolve_author_user_ids(db, articles)
    user_ids = {uid for uid in author_ids.values() if uid}
    email_by_id: dict[int, str] = {}
    if user_ids:
        for row in db.query(models.User.id, models.User.email).filter(models.User.id.in_(user_ids)).all():
            email_by_id[int(row.id)] = (row.email or "").strip() or None
    rows: list[KbAdminListRow] = []
    for article in articles:
        uid = author_ids.get(article.id)
        rows.append(
            KbAdminListRow(
                article=article,
                author_email=email_by_id.get(uid) if uid else None,
            )
        )
    return rows
