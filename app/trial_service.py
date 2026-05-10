"""Experience 플랜 체험 기간 부여( Junior entitlement와 동일 ). SiteSettings experience_trial_days."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models


def _trial_pepper() -> str:
    return (
        os.environ.get("SUBSCRIPTION_TRIAL_PEPPER")
        or os.environ.get("SECRET_KEY")
        or "dev-trial-pepper-change-me"
    )


def trial_identity_hash(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    body = (raw or "").strip().lower()
    h = hashlib.sha256(f"{_trial_pepper()}\0{k}\0{body}".encode("utf-8")).hexdigest()
    return h


def get_experience_trial_days(db: Session) -> int:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == "experience_trial_days").first()
    raw = (getattr(row, "value", None) or "").strip() if row else ""
    if not raw:
        return 14
    try:
        return max(1, min(3650, int(raw)))
    except ValueError:
        return 14


def maybe_grant_experience_trial(db: Session, user: models.User) -> None:
    """이메일·휴대폰 모두 인증된 Experience 회원에게 1회 체험 기간 설정."""
    if getattr(user, "is_admin", False):
        return
    code = (getattr(user, "subscription_plan_code", None) or "").strip().lower()
    if code != "experience":
        return
    if getattr(user, "experience_trial_ends_at", None):
        return
    if not user.email_verified or not getattr(user, "phone_verified", False):
        return
    email = (user.email or "").strip().lower()
    phone = (getattr(user, "phone_number", None) or "").strip()
    if not email or not phone:
        return

    h_email = trial_identity_hash("email", email)
    h_phone = trial_identity_hash("phone", phone)
    exists = (
        db.query(models.TrialEligibilityConsumed)
        .filter(
            models.TrialEligibilityConsumed.kind == "email",
            models.TrialEligibilityConsumed.identity_hash == h_email,
        )
        .first()
    ) or (
        db.query(models.TrialEligibilityConsumed)
        .filter(
            models.TrialEligibilityConsumed.kind == "phone",
            models.TrialEligibilityConsumed.identity_hash == h_phone,
        )
        .first()
    )
    if exists:
        return

    anchor_candidates = [d for d in (getattr(user, "created_at", None), getattr(user, "phone_verified_at", None)) if d is not None]
    anchor = max(anchor_candidates) if anchor_candidates else datetime.utcnow()
    days = get_experience_trial_days(db)
    user.experience_trial_ends_at = anchor + timedelta(days=int(days))
    db.add(
        models.TrialEligibilityConsumed(kind="email", identity_hash=h_email, created_at=datetime.utcnow())
    )
    db.add(
        models.TrialEligibilityConsumed(kind="phone", identity_hash=h_phone, created_at=datetime.utcnow())
    )
    db.add(user)
