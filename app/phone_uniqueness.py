"""휴대폰 번호 중복 정책 — allow_shared_phone 시 다른 계정과 동일 번호 허용."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


def phone_blocked_by_other_user(db: Session, phone_e164: str, user_id: int) -> bool:
    """True면 이 사용자가 phone_e164 로 인증·저장할 수 없음."""
    phone = (phone_e164 or "").strip()
    if not phone:
        return False

    actor = db.query(models.User).filter(models.User.id == user_id).first()
    if actor and bool(getattr(actor, "allow_shared_phone", False)):
        return False

    other = (
        db.query(models.User)
        .filter(
            models.User.id != user_id,
            models.User.phone_number == phone,
        )
        .first()
    )
    return other is not None
