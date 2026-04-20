"""
SMTP 발송 (회원 이메일 인증 링크). SMTP_HOST + MAIL_FROM 이 설정된 경우에만 활성화.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def smtp_verification_enabled() -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    mail_from = (os.environ.get("MAIL_FROM") or "").strip()
    return bool(host and mail_from)


def _smtp_params() -> dict:
    return {
        "host": (os.environ.get("SMTP_HOST") or "").strip(),
        "port": int(os.environ.get("SMTP_PORT") or "587"),
        "user": (os.environ.get("SMTP_USER") or "").strip(),
        "password": (os.environ.get("SMTP_PASSWORD") or "").strip(),
        "mail_from": (os.environ.get("MAIL_FROM") or "").strip(),
    }


def send_verification_email(to_addr: str, verify_url: str) -> None:
    if not smtp_verification_enabled():
        raise RuntimeError("SMTP is not configured")
    p = _smtp_params()
    subject = os.environ.get("MAIL_VERIFY_SUBJECT", "[SAP Dev Hub] 이메일 주소를 확인해 주세요")
    body = (
        "아래 링크를 눌러 이메일 인증을 완료해 주세요.\n\n"
        f"{verify_url}\n\n"
        "이 링크는 며칠 동안만 유효합니다. 요청하지 않으셨다면 이 메일을 무시하세요."
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = p["mail_from"]
    msg["To"] = to_addr
    msg.set_content(body)

    if p["port"] == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(p["host"], p["port"], context=context) as smtp:
            if p["user"]:
                smtp.login(p["user"], p["password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(p["host"], p["port"]) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            if p["user"]:
                smtp.login(p["user"], p["password"])
            smtp.send_message(msg)
