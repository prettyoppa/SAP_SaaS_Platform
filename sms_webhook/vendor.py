"""Naver SENS (+82) / Twilio (global) — SAP 앱 sms_sender payload와 동일 계약."""

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


def sens_configured() -> bool:
    return all(
        [
            (os.environ.get("NCP_SENS_ACCESS_KEY") or "").strip(),
            (os.environ.get("NCP_SENS_SECRET_KEY") or "").strip(),
            (os.environ.get("NCP_SENS_SERVICE_ID") or "").strip(),
            (os.environ.get("NCP_SENS_SENDER") or "").strip(),
        ]
    )


def twilio_configured() -> bool:
    return all(
        [
            (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip(),
            (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip(),
            (os.environ.get("TWILIO_FROM_NUMBER") or "").strip(),
        ]
    )


def kr_e164_to_local_digits(phone_e164: str) -> str:
    if not phone_e164.startswith("+82"):
        raise ValueError("not +82")
    rest = phone_e164[3:]
    if not rest.isdigit():
        raise ValueError("invalid national number")
    if not rest.startswith("0"):
        return "0" + rest
    return rest


def send_sens_sms(phone_e164: str, body: str) -> None:
    access = (os.environ.get("NCP_SENS_ACCESS_KEY") or "").strip()
    secret = (os.environ.get("NCP_SENS_SECRET_KEY") or "").strip()
    service_id = (os.environ.get("NCP_SENS_SERVICE_ID") or "").strip()
    sender = (os.environ.get("NCP_SENS_SENDER") or "").strip()

    to_local = kr_e164_to_local_digits(phone_e164)
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
                raise RuntimeError(f"SENS failed statusCode={status_code} body={raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SENS HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SENS connection failed: {e}") from e


def send_twilio_sms(phone_e164: str, body: str) -> None:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    form = urllib.parse.urlencode({"To": phone_e164, "From": from_num, "Body": body}).encode("utf-8")
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
        raise RuntimeError(f"Twilio connection failed: {e}") from e


def deliver_sms(phone_e164: str, body: str) -> str:
    """Returns route used: sens | twilio."""
    phone = (phone_e164 or "").strip()
    if phone.startswith("+82"):
        if not sens_configured():
            raise RuntimeError("SENS not configured for +82")
        send_sens_sms(phone, body)
        return "sens"
    if not twilio_configured():
        raise RuntimeError("Twilio not configured for non-+82")
    send_twilio_sms(phone, body)
    return "twilio"
