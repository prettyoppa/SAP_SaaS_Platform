"""검색엔진 유입(직접 접속 제외) 시 관리자 SMS 알림."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from . import auth, models
from .database import SessionLocal
from .sms_sender import send_offer_inquiry_sms, sms_enabled
from .wallet_topup_notifications import _admin_alert_sms, _admin_ops_recipients

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# (referer host에 포함되면 매칭, SMS에 쓸 짧은 라벨)
_SEARCH_ENGINE_HOST_RULES: tuple[tuple[str, str], ...] = (
    ("google.", "Google"),
    ("naver.com", "Naver"),
    ("search.naver.com", "Naver"),
    ("bing.com", "Bing"),
    ("duckduckgo.com", "DuckDuckGo"),
    ("yahoo.", "Yahoo"),
    ("search.yahoo.com", "Yahoo"),
    ("daum.net", "Daum"),
    ("search.daum.net", "Daum"),
    ("ecosia.org", "Ecosia"),
    ("baidu.com", "Baidu"),
    ("yandex.", "Yandex"),
)

_BOT_UA_MARKERS = (
    "bot",
    "spider",
    "crawler",
    "slurp",
    "preview",
    "headless",
    "google-inspectiontool",
)

_SKIP_PATH_PREFIXES = (
    "/static/",
    "/api/",
    "/health",
    "/google",
    "/favicon",
)

_rate_lock = threading.Lock()
_rate_last_sent: dict[str, float] = {}


def search_referral_alerts_enabled() -> bool:
    v = (os.environ.get("SEARCH_REFERRAL_SMS_ENABLED") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _cooldown_seconds() -> int:
    try:
        return max(60, int(os.environ.get("SEARCH_REFERRAL_SMS_COOLDOWN_SEC") or "600"))
    except ValueError:
        return 600


def _normalize_host(host: str | None) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _same_site(referer_host: str, site_host: str) -> bool:
    r = _normalize_host(referer_host)
    s = _normalize_host(site_host)
    if not r or not s:
        return False
    if r == s:
        return True
    return r.endswith("." + s) or s.endswith("." + r)


def classify_search_referrer(referer: str | None, *, site_host: str) -> str | None:
    """
  직접 접속(Referer 없음)·자사 도메인·비검색 Referer → None.
  검색엔진 Referer → 짧은 소스명(Google, Naver, …).
    """
    raw = (referer or "").strip()
    if not raw:
        return None
    try:
        ref_host = urlparse(raw).netloc or ""
    except Exception:
        return None
    if not ref_host or _same_site(ref_host, site_host):
        return None
    ref_l = _normalize_host(ref_host)
    for needle, label in _SEARCH_ENGINE_HOST_RULES:
        if needle in ref_l:
            return label
    return None


def _should_inspect_request(method: str, path: str) -> bool:
    if (method or "").upper() != "GET":
        return False
    p = (path or "").split("?", 1)[0]
    if not p.startswith("/"):
        return False
    for prefix in _SKIP_PATH_PREFIXES:
        if p.startswith(prefix):
            return False
    if p.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".woff2")):
        return False
    return True


def _is_probable_bot(user_agent: str | None) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return False
    return any(m in ua for m in _BOT_UA_MARKERS)


def _rate_limit_ok(client_ip: str, engine: str) -> bool:
    key = f"{client_ip}|{engine}"
    now = time.monotonic()
    cooldown = float(_cooldown_seconds())
    with _rate_lock:
        last = _rate_last_sent.get(key)
        if last is not None and (now - last) < cooldown:
            return False
        _rate_last_sent[key] = now
        if len(_rate_last_sent) > 5000:
            cutoff = now - cooldown * 2
            for k in list(_rate_last_sent.keys()):
                if _rate_last_sent[k] < cutoff:
                    del _rate_last_sent[k]
    return True


def _notify_admins_search_referral(db: Session, search_source: str) -> None:
    body = f"[SAP Dev Hub] {search_source}+접속확인"
    for admin in _admin_ops_recipients(db):
        sms_ok, phone = _admin_alert_sms(admin)
        if not sms_ok or not phone:
            continue
        try:
            send_offer_inquiry_sms(phone, body, sms_type="search_referral")
        except Exception:
            logger.exception("search referral sms failed admin_id=%s", admin.id)


def _process_search_referral(
    *,
    referer: str | None,
    site_host: str,
    path: str,
    client_ip: str,
    user_agent: str | None,
    skip_admin_session: bool,
) -> None:
    if not search_referral_alerts_enabled() or not sms_enabled():
        return
    if skip_admin_session or _is_probable_bot(user_agent):
        return
    if not _should_inspect_request("GET", path):
        return
    engine = classify_search_referrer(referer, site_host=site_host)
    if not engine:
        return
    if not _rate_limit_ok(client_ip or "unknown", engine):
        return
    db = SessionLocal()
    try:
        _notify_admins_search_referral(db, engine)
        logger.info("search referral alert sent source=%s path=%s ip=%s", engine, path, client_ip)
    finally:
        db.close()


def schedule_search_referral_check(request: Request) -> None:
    """미들웨어에서 호출 — 응답 지연 없이 백그라운드 처리."""
    if not search_referral_alerts_enabled():
        return
    referer = request.headers.get("referer") or request.headers.get("referrer")
    site_host = request.url.hostname or request.headers.get("host") or ""
    path = request.url.path or "/"
    client_ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent")

    skip_admin = False
    u = getattr(request.state, "current_user", None)
    if u and getattr(u, "is_admin", False):
        skip_admin = True

    def _run() -> None:
        try:
            _process_search_referral(
                referer=referer,
                site_host=site_host,
                path=path,
                client_ip=client_ip,
                user_agent=user_agent,
                skip_admin_session=skip_admin,
            )
        except Exception:
            logger.exception("search_referral_alert background failed")

    threading.Thread(target=_run, daemon=True).start()
