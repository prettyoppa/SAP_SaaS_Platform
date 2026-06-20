"""회원 주요 이벤트 — 관리자 시간별 digest 알림(이메일·SMS)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from . import models
from .email_smtp import send_plain_notification_email
from .platform_audit import event_label
from .wallet_topup_notifications import (
    _admin_alert_email,
    _admin_alert_sms,
    _admin_ops_recipients,
    _admin_ops_sms_env_phones,
    _send_admin_sms_to_phone,
)

logger = logging.getLogger(__name__)

SETTING_EMAIL = "audit_digest_email_enabled"
SETTING_SMS = "audit_digest_sms_enabled"
SETTING_LAST_SENT = "audit_digest_last_sent_at"
SETTING_LAST_EVENT_ID = "audit_digest_last_event_id"

AUDIT_DIGEST_SETTING_KEYS = (SETTING_EMAIL, SETTING_SMS, SETTING_LAST_SENT, SETTING_LAST_EVENT_ID)


def _setting(db: Session, key: str) -> str:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    return (row.value or "").strip() if row else ""


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(models.SiteSettings).filter(models.SiteSettings.key == key).first()
    if row is None:
        row = models.SiteSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def digest_email_enabled(db: Session) -> bool:
    return _setting(db, SETTING_EMAIL) == "1"


def digest_sms_enabled(db: Session) -> bool:
    return _setting(db, SETTING_SMS) == "1"


def _parse_last_sent(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _format_last_sent(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_last_event_id(raw: str) -> int:
    try:
        return max(0, int((raw or "").strip()))
    except ValueError:
        return 0


def _effective_last_event_id(db: Session) -> int:
    """이미 전송한 마지막 이벤트 id. 레거시 시각 워터마크가 있으면 1회 부트스트랩."""
    from sqlalchemy import func

    stored = _parse_last_event_id(_setting(db, SETTING_LAST_EVENT_ID))
    if stored > 0:
        return stored
    since = _parse_last_sent(_setting(db, SETTING_LAST_SENT))
    if since is None:
        return 0
    legacy_max = (
        db.query(func.max(models.PlatformAuditEvent.id))
        .filter(models.PlatformAuditEvent.created_at <= since)
        .scalar()
    )
    return int(legacy_max or 0)


def pending_events(db: Session, after_event_id: int = 0) -> list[models.PlatformAuditEvent]:
    q = db.query(models.PlatformAuditEvent).order_by(
        models.PlatformAuditEvent.id.asc(),
    )
    if after_event_id > 0:
        q = q.filter(models.PlatformAuditEvent.id > after_event_id)
    return q.all()


def group_events_by_actor(events: Iterable[models.PlatformAuditEvent]) -> dict[str, list[models.PlatformAuditEvent]]:
    grouped: dict[str, list[models.PlatformAuditEvent]] = defaultdict(list)
    for evt in events:
        email = (evt.actor_email or "").strip().lower()
        if email:
            grouped[email].append(evt)
    return dict(grouped)


def build_digest_email_body(events: list[models.PlatformAuditEvent]) -> str:
    grouped = group_events_by_actor(events)
    lines = [f"회원 주요 이벤트 요약 ({len(events)}건)", ""]
    for email in sorted(grouped.keys()):
        lines.append(email)
        for evt in grouped[email]:
            label = event_label(evt.event_type, lang="ko")
            if evt.detail:
                lines.append(f"  · {label} — {evt.detail}")
            else:
                lines.append(f"  · {label}")
        lines.append("")
    lines.append("— SAP Dev Hub 운영 알림")
    return "\n".join(lines).strip()


def build_digest_sms_body(events: list[models.PlatformAuditEvent], *, max_len: int = 900) -> str:
    grouped = group_events_by_actor(events)
    parts: list[str] = []
    for email in sorted(grouped.keys()):
        labels = [event_label(e.event_type, lang="ko") for e in grouped[email]]
        short = email if len(email) <= 28 else email[:25] + "…"
        parts.append(f"{short}: {', '.join(labels)}")
    body = f"[회원이벤트] {len(events)}건 — " + "; ".join(parts)
    if len(body) <= max_len:
        return body
    return f"[회원이벤트] {len(events)}건 (상세는 이메일 참고)"


def _notify_admins_email(db: Session, subject: str, body: str) -> None:
    for admin in _admin_ops_recipients(db):
        ok, addr = _admin_alert_email(admin)
        if ok and addr:
            send_plain_notification_email(addr, subject, body)


def _notify_admins_sms(db: Session, body: str) -> None:
    seen: set[str] = set()
    for admin in _admin_ops_recipients(db):
        ok, phone = _admin_alert_sms(admin)
        if ok and phone and phone not in seen:
            seen.add(phone)
            _send_admin_sms_to_phone(phone, body, sms_type="audit_digest_admin")
    for phone in _admin_ops_sms_env_phones():
        if phone not in seen:
            seen.add(phone)
            _send_admin_sms_to_phone(phone, body, sms_type="audit_digest_admin")


def run_audit_digest(db: Session) -> int:
    """
    마지막 전송 시각 이후 이벤트를 조회해 관리자 digest 발송.
    반환: 처리한 이벤트 건수(0이면 알림 없음).
    """
    if not digest_email_enabled(db) and not digest_sms_enabled(db):
        return 0

    after_id = _effective_last_event_id(db)
    events = pending_events(db, after_id)
    if not events:
        return 0

    last_id = max(int(evt.id) for evt in events)
    watermark = max((evt.created_at for evt in events if evt.created_at), default=datetime.utcnow())
    _set_setting(db, SETTING_LAST_EVENT_ID, str(last_id))
    _set_setting(db, SETTING_LAST_SENT, _format_last_sent(watermark))
    db.commit()

    subject = f"[SAP Dev Hub] 회원 주요 이벤트 ({len(events)}건)"
    email_body = build_digest_email_body(events)
    sms_body = build_digest_sms_body(events)

    if digest_email_enabled(db):
        try:
            _notify_admins_email(db, subject, email_body)
        except Exception:
            logger.exception("audit digest email failed")

    if digest_sms_enabled(db):
        try:
            _notify_admins_sms(db, sms_body)
        except Exception:
            logger.exception("audit digest sms failed")

    return len(events)
