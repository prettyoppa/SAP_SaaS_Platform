"""
휴대폰 OTP 문자 발송.

경로:
- 수신번호가 +82(대한민국)로 시작: 네이버 클라우드 SENS (환경변수 설정 시).
- 그 외: Twilio (환경변수 설정 시).
- 위 API가 해당 구간에 준비되지 않은 경우: SMS_WEBHOOK_URL 이 있으면 JSON POST 위임.
- 모두 없으면 개발용으로 서버 로그만 남김.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


def sms_enabled() -> bool:
    return bool(
        _sens_configured()
        or _twilio_configured()
        or (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    )


def _registration_otp_ttl_minutes() -> int:
    try:
        return max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        return 10


def send_registration_otp_sms(phone_e164: str, code: str) -> None:
    ttl = _registration_otp_ttl_minutes()
    body = f"[SAP Dev Hub] 인증번호 {code} (유효 {ttl}분)"
    phone = (phone_e164 or "").strip()

    if phone.startswith("+82") and _sens_configured():
        _send_sens_sms(phone, body)
        return
    if not phone.startswith("+82") and _twilio_configured():
        _send_twilio_sms(phone, body)
        return

    webhook = (os.environ.get("SMS_WEBHOOK_URL") or "").strip()
    if not webhook:
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
    """+8210… → 010… 형태(콘솔 등록 발신·착신 형식에 맞춤)."""
    if not phone_e164.startswith("+82"):
        raise ValueError("not +82")
    rest = phone_e164[3:]
    if not rest.isdigit():
        raise ValueError("invalid national number")
    if not rest.startswith("0"):
        return "0" + rest
    return rest


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

    # 한글 본문 길이 대비 LMS 사용
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
        with urllib.request.urlopen(req, timeout=20) as resp:
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
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"Twilio HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twilio HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Twilio 연결 실패: {e}") from e
