"""
휴대폰 SMS 발송.

1. SMS_WEBHOOK_URL 이 있으면 웹훅 우선 (502/503/504·연결 실패 시 짧게 재시도).
2. 웹훅 실패 시 메인 앱에 NCP_SENS_* / TWILIO_* 가 있으면 직접 발송.
3. 모두 없으면 개발용 로그만.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

_log = logging.getLogger(__name__)

_WEBHOOK_RETRY_CODES = frozenset({502, 503, 504})
_WEBHOOK_MAX_ATTEMPTS = 3
_WEBHOOK_RETRY_SLEEP_SEC = 1.5


def sms_enabled() -> bool:
    return bool(
        (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
        or _sens_configured()
        or _twilio_configured()
    )


def _registration_otp_ttl_minutes() -> int:
    try:
        return max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        return 10


def _sens_configured() -> bool:
    return all(
        [
            (os.environ.get("NCP_SENS_ACCESS_KEY") or "").strip(),
            (os.environ.get("NCP_SENS_SECRET_KEY") or "").strip(),
            (os.environ.get("NCP_SENS_SERVICE_ID") or "").strip(),
            (os.environ.get("NCP_SENS_SENDER") or "").strip(),
        ]
    )


def _twilio_configured() -> bool:
    return all(
        [
            (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip(),
            (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip(),
            (os.environ.get("TWILIO_FROM_NUMBER") or "").strip(),
        ]
    )


def _kr_e164_to_local_digits(phone_e164: str) -> str:
    if not phone_e164.startswith("+82"):
        raise ValueError("not +82")
    rest = phone_e164[3:]
    if not rest.isdigit():
        raise ValueError("invalid national number")
    if not rest.startswith("0"):
        return "0" + rest
    return rest


def _webhook_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret = (os.environ.get("SMS_WEBHOOK_SECRET") or "").strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def _post_sms_webhook(webhook: str, phone: str, body: str, sms_type: str) -> None:
    route = "domestic_kr_sens" if phone.startswith("+82") else "global_twilio"
    payload = {
        "to": phone,
        "text": body,
        "type": sms_type,
        "route_hint": route,
        "country_hint": "KR" if phone.startswith("+82") else "GLOBAL",
    }
    data = json.dumps(payload).encode("utf-8")
    last_err: Exception | None = None

    for attempt in range(1, _WEBHOOK_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            webhook,
            data=data,
            headers=_webhook_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                if resp.status >= 400:
                    raw = resp.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"SMS webhook HTTP {resp.status}: {raw}")
            return
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"SMS webhook {e.code}: {err_body}")
            if e.code in _WEBHOOK_RETRY_CODES and attempt < _WEBHOOK_MAX_ATTEMPTS:
                _log.warning(
                    "sms webhook retry %s/%s type=%s code=%s",
                    attempt,
                    _WEBHOOK_MAX_ATTEMPTS,
                    sms_type,
                    e.code,
                )
                time.sleep(_WEBHOOK_RETRY_SLEEP_SEC)
                continue
            raise last_err from e
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"SMS webhook 연결 실패: {e}")
            if attempt < _WEBHOOK_MAX_ATTEMPTS:
                _log.warning(
                    "sms webhook retry %s/%s type=%s url error",
                    attempt,
                    _WEBHOOK_MAX_ATTEMPTS,
                    sms_type,
                )
                time.sleep(_WEBHOOK_RETRY_SLEEP_SEC)
                continue
            raise last_err from e

    if last_err:
        raise last_err


def _send_sens_sms(phone_e164: str, body: str) -> None:
    access = (os.environ.get("NCP_SENS_ACCESS_KEY") or "").strip()
    secret = (os.environ.get("NCP_SENS_SECRET_KEY") or "").strip()
    service_id = (os.environ.get("NCP_SENS_SERVICE_ID") or "").strip()
    sender = (os.environ.get("NCP_SENS_SENDER") or "").strip()

    to_local = _kr_e164_to_local_digits(phone_e164)
    path = f"/sms/v2/services/{service_id}/messages"
    url = f"https://sens.apigw.ntruss.com{path}"
    timestamp = str(int(time.time() * 1000))
    sign_msg = f"POST {path}\n{timestamp}\n{access}"
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), sign_msg.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    payload = {
        "type": "LMS",
        "contentType": "COMM",
        "countryCode": "82",
        "from": sender,
        "content": body,
        "messages": [{"to": to_local}],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "x-ncp-apigw-timestamp": timestamp,
            "x-ncp-iam-access-key": access,
            "x-ncp-apigw-signature-v2": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"SENS HTTP {resp.status}: {raw}")
            try:
                meta = json.loads(raw)
            except json.JSONDecodeError:
                meta = {}
            status_code = str(meta.get("statusCode") or "")
            if status_code and status_code != "202":
                raise RuntimeError(f"SENS 실패 statusCode={status_code} body={raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SENS HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SENS 연결 실패: {e}") from e


def _send_twilio_sms(phone_e164: str, body: str) -> None:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    form = urllib.parse.urlencode(
        {"To": phone_e164, "From": from_num, "Body": body}
    ).encode("utf-8")
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        data=form,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"Twilio HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twilio HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Twilio 연결 실패: {e}") from e


def _send_direct_vendor(phone: str, body: str) -> None:
    if phone.startswith("+82") and _sens_configured():
        _send_sens_sms(phone, body)
        return
    if not phone.startswith("+82") and _twilio_configured():
        _send_twilio_sms(phone, body)
        return
    if phone.startswith("+82"):
        raise RuntimeError("SENS 환경변수가 설정되지 않았습니다 (NCP_SENS_*)")
    raise RuntimeError("Twilio 환경변수가 설정되지 않았습니다 (TWILIO_*)")


def _direct_available(phone: str) -> bool:
    if phone.startswith("+82"):
        return _sens_configured()
    return _twilio_configured()


def _deliver_sms(phone_e164: str, body: str, *, sms_type: str) -> None:
    phone = (phone_e164 or "").strip()
    text = (body or "").strip()
    if not phone or not text:
        raise ValueError("phone and body required")

    webhook = (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    webhook_err: Exception | None = None

    if webhook:
        try:
            _post_sms_webhook(webhook, phone, text, sms_type)
            return
        except Exception as exc:
            webhook_err = exc
            _log.warning("sms webhook failed type=%s: %s", sms_type, exc)

    if _direct_available(phone):
        try:
            _send_direct_vendor(phone, text)
            if webhook_err:
                _log.info(
                    "sms delivered via direct vendor after webhook failure type=%s",
                    sms_type,
                )
            return
        except Exception:
            if webhook_err:
                raise webhook_err
            raise

    if webhook_err:
        raise webhook_err

    print(f"[SMS MOCK {sms_type}] to={phone} body={text[:200]}...")


def send_offer_inquiry_sms(phone_e164: str, body: str, *, sms_type: str = "offer_inquiry") -> None:
    """문의·오퍼·매칭 등 트랜잭션 SMS."""
    _deliver_sms(phone_e164, body, sms_type=sms_type)


def send_registration_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 인증번호 {code} (유효 {ttl}분)"
    _deliver_sms(phone_e164, body, sms_type="registration_otp")


def send_account_phone_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 계정 휴대폰 인증번호 {code} (유효 {ttl}분)"
    _deliver_sms(phone_e164, body, sms_type="account_phone_otp")


def send_email_hint_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 이메일 찾기 인증번호 {code} (유효 {ttl}분)"
    _deliver_sms(phone_e164, body, sms_type="email_hint_otp")
