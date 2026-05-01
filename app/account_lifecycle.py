"""회원 탈퇴(유예 후 영구 삭제) 및 관련 purge."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from . import models

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def deletion_grace_days() -> int:
    try:
        return max(1, min(90, int(os.environ.get("ACCOUNT_DELETION_GRACE_DAYS") or "14")))
    except ValueError:
        return 14


def _admins_txt_emails() -> set[str]:
    path = Path(__file__).resolve().parent.parent / "admins.txt"
    emails: set[str] = set()
    if not path.exists():
        return emails
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            emails.add(line.lower())
    return emails


def refresh_admin_flag_for_user(db: Session, u: models.User) -> None:
    """이메일 변경 후 admins.txt 기준으로 해당 사용자의 is_admin만 동기화(커밋은 호출자)."""
    admin_emails = _admins_txt_emails()
    want = u.email.lower() in admin_emails
    if u.is_admin != want:
        u.is_admin = want
    db.add(u)


def purge_user_and_owned_data(db: Session, target_user_id: int) -> None:
    """사용자 행과 소유 데이터 삭제 (관리자 테스트 삭제·유예 만료 하드 삭제 공통)."""
    uid = target_user_id
    u = db.query(models.User).filter(models.User.id == uid).first()
    if not u:
        return

    email_norm = (u.email or "").strip().lower()

    db.query(models.EmailChangePending).filter(models.EmailChangePending.user_id == uid).delete(
        synchronize_session=False
    )

    if email_norm:
        db.query(models.EmailRegistrationCode).filter(
            models.EmailRegistrationCode.email == email_norm
        ).delete(synchronize_session=False)

    rfp_ids = [row[0] for row in db.query(models.RFP.id).filter(models.RFP.user_id == uid).all()]
    if rfp_ids:
        db.query(models.IntegrationRequest).filter(
            models.IntegrationRequest.workflow_rfp_id.in_(rfp_ids)
        ).update({models.IntegrationRequest.workflow_rfp_id: None}, synchronize_session=False)
        db.query(models.AbapAnalysisRequest).filter(
            models.AbapAnalysisRequest.workflow_rfp_id.in_(rfp_ids)
        ).update({models.AbapAnalysisRequest.workflow_rfp_id: None}, synchronize_session=False)

    for row in db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.user_id == uid).all():
        db.delete(row)

    for row in db.query(models.IntegrationRequest).filter(models.IntegrationRequest.user_id == uid).all():
        db.delete(row)

    for rfp in db.query(models.RFP).filter(models.RFP.user_id == uid).all():
        db.query(models.RFPMessage).filter(models.RFPMessage.rfp_id == rfp.id).delete(synchronize_session=False)
        db.query(models.RfpFsSupplement).filter(models.RfpFsSupplement.rfp_id == rfp.id).delete(
            synchronize_session=False
        )
        db.delete(rfp)

    db.query(models.ABAPCode).filter(models.ABAPCode.uploaded_by == uid).delete(synchronize_session=False)

    rev_ids = [row[0] for row in db.query(models.Review.id).filter(models.Review.user_id == uid).all()]
    if rev_ids:
        db.query(models.ReviewComment).filter(models.ReviewComment.review_id.in_(rev_ids)).delete(
            synchronize_session=False
        )
    db.query(models.Review).filter(models.Review.user_id == uid).delete(synchronize_session=False)
    db.query(models.ReviewComment).filter(models.ReviewComment.user_id == uid).delete(synchronize_session=False)

    db.delete(u)
    db.commit()


def run_scheduled_hard_deletes(db: Session) -> int:
    """탈퇴 유예가 지난 계정을 영구 삭제. 처리 건수 반환."""
    now = datetime.utcnow()
    candidates = (
        db.query(models.User)
        .filter(
            models.User.pending_account_deletion.is_(True),
            models.User.deletion_hard_scheduled_at.isnot(None),
            models.User.deletion_hard_scheduled_at <= now,
        )
        .all()
    )
    n = 0
    for u in candidates:
        uid = u.id
        try:
            purge_user_and_owned_data(db, uid)
            n += 1
        except Exception:
            logger.exception("scheduled purge failed user_id=%s", uid)
            db.rollback()
    return n
