"""
휴대폰 OTP 문자 발송 유틸.

기본 동작:
- SMS_WEBHOOK_URL 미설정: 실제 발송 없이 서버 로그에만 남김(개발용).
- SMS_WEBHOOK_URL 설정: JSON POST로 외부 발송 서비스에 위임.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional


def sms_enabled() -> bool:
    return bool((os.environ.get("SMS_WEBHOOK_URL") or "").strip())


def send_registration_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 인증번호 {code} (유효 {ttl}분)"
    webhook = (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    if not webhook:
        # 개발 단계: 실제 발송 없이 로그 대체
        print(f"[SMS MOCK] to={phone_e164} body={body}")
        return

    payload = {
        "to": phone_e164,
        "text": body,
        "type": "registration_otp",
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


def _registration_otp_ttl_minutes() -> int:
    try:
        return max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        return 10
