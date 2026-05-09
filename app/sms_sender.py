"""
휴대폰 OTP 문자 발송.

앱은 벤더를 직접 호출하지 않고 SMS 웹훅 한 곳만 호출한다.
국내(+82) SENS / 해외 Twilio 분기는 웹훅 서비스에서 처리한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def sms_enabled() -> bool:
    return bool((os.environ.get("SMS_WEBHOOK_URL") or "").strip())


def _registration_otp_ttl_minutes() -> int:
    try:
        return max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        return 10


def send_offer_inquiry_sms(phone_e164: str, body: str) -> None:
    """컨설턴트에게 요청 문의 SMS (웹훅 경유)."""
    phone = (phone_e164 or "").strip()
    webhook = (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    if not webhook:
        print(f"[SMS MOCK offer_inquiry] to={phone} body={body[:200]}...")
        return
    route = "domestic_kr_sens" if phone.startswith("+82") else "global_twilio"
    payload = {
        "to": phone,
        "text": body,
        "type": "offer_inquiry",
        "route_hint": route,
        "country_hint": "KR" if phone.startswith("+82") else "GLOBAL",
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"SMS webhook HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SMS webhook {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SMS webhook 연결 실패: {e}") from e


def send_registration_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 인증번호 {code} (유효 {ttl}분)"
    phone = (phone_e164 or "").strip()

    webhook = (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    if not webhook:
        print(f"[SMS MOCK] to={phone} body={body}")
        return

    # 웹훅이 벤더 분기에 바로 쓸 수 있도록 힌트를 함께 전달한다.
    route = "domestic_kr_sens" if phone.startswith("+82") else "global_twilio"
    payload = {
        "to": phone,
        "text": body,
        "type": "registration_otp",
        "route_hint": route,
        "country_hint": "KR" if phone.startswith("+82") else "GLOBAL",
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"SMS webhook HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SMS webhook {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SMS webhook 연결 실패: {e}") from e
