"""
SMTP 발송 (회원 이메일 인증 링크). SMTP_HOST + MAIL_FROM 이 설정된 경우에만 활성화.
"""
from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage


def smtp_verification_enabled() -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    mail_from = (os.environ.get("MAIL_FROM") or "").strip()
    return bool(host and mail_from)


def _smtp_timeout_sec() -> float:
    try:
        return float(os.environ.get("SMTP_TIMEOUT_SEC") or "30")
    except ValueError:
        return 30.0


def _smtp_ehlo_hostname() -> str | None:
    h = (os.environ.get("SMTP_EHLO_HOSTNAME") or "").strip()
    return h or None


def _smtp_force_ipv4() -> bool:
    """Railway/Docker 등에서 IPv6 라우트가 없을 때 smtp.gmail.com 연결이 Errno 101로 실패하는 경우가 있어 IPv4만 사용."""
    v = (os.environ.get("SMTP_FORCE_IPV4") or "1").strip().lower()
    return v in ("1", "true", "yes", "")


def _ipv4_socket_connect(
    host: str,
    port: int,
    timeout: float,
    source_address: tuple | None = None,
) -> socket.socket:
    """AF_INET만 사용해 connect (IPv6 ENETUNREACH 회피)."""
    last_exc: OSError | None = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        af, socktype, proto, _canon, sa = res
        sock = socket.socket(af, socktype, proto)
        sock.settimeout(timeout)
        if source_address:
            sock.bind(source_address)
        try:
            sock.connect(sa)
            return sock
        except OSError as e:
            last_exc = e
            sock.close()
    if last_exc:
        raise last_exc
    raise OSError(f"IPv4 connect failed for {host!r}:{port}")


class _SMTP_IPv4(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        if not _smtp_force_ipv4():
            return super()._get_socket(host, port, timeout)
        if self.debuglevel > 0:
            self._print_debug("connect: to", (host, port))
        return _ipv4_socket_connect(host, port, timeout, self.source_address)


class _SMTP_SSL_IPv4(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        if not _smtp_force_ipv4():
            return super()._get_socket(host, port, timeout)
        if self.debuglevel > 0:
            self._print_debug("connect:", (host, port))
        new_socket = _ipv4_socket_connect(host, port, timeout, self.source_address)
        self.sock = self.context.wrap_socket(new_socket, server_hostname=host)
        return self.sock


def _smtp_params() -> dict:
    return {
        "host": (os.environ.get("SMTP_HOST") or "").strip(),
        "port": int(os.environ.get("SMTP_PORT") or "587"),
        "user": (os.environ.get("SMTP_USER") or "").strip(),
        "password": (os.environ.get("SMTP_PASSWORD") or "").strip(),
        "mail_from": (os.environ.get("MAIL_FROM") or "").strip(),
    }


def log_smtp_startup_checks(root_logger: logging.Logger) -> None:
    """
    Railway 등에서 변수 누락·오타를 빨리 찾기 위해 기동 시 한 번 로그합니다.
    비밀번호 값은 절대 출력하지 않습니다.
    """
    if not smtp_verification_enabled():
        root_logger.info("[SMTP] email verification disabled (set SMTP_HOST + MAIL_FROM to enable)")
        return
    p = _smtp_params()
    pub = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    if pub and not (pub.startswith("https://") or pub.startswith("http://")):
        root_logger.error(
            "[SMTP] PUBLIC_BASE_URL must include scheme, e.g. https://sap.example.com (got: %s)",
            pub[:80],
        )
    elif not pub:
        root_logger.warning(
            "[SMTP] PUBLIC_BASE_URL is empty; verify links will use request host (set explicitly behind proxies)"
        )
    root_logger.info(
        "[SMTP] enabled host=%s port=%s mail_from_set=%s user_set=%s password_set=%s",
        p["host"] or "(empty)",
        p["port"],
        bool(p["mail_from"]),
        bool(p["user"]),
        bool(p["password"]),
    )
    if not p["user"] or not p["password"]:
        root_logger.error(
            "[SMTP] SMTP_USER (full Gmail address) and SMTP_PASSWORD (16-char app password) are required — "
            "verification emails will fail until both are set."
        )
    if "gmail" in p["host"].lower() and p["port"] not in (587, 465):
        root_logger.warning("[SMTP] Gmail usually uses port 587 or 465; current port=%s", p["port"])
    root_logger.info(
        "[SMTP] SMTP_FORCE_IPV4=%s (if connect fails with Errno 101, keep enabled)",
        _smtp_force_ipv4(),
    )
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
        root_logger.warning(
            "[SMTP] Railway: Free/Trial/Hobby 워크스페이스는 아웃바운드 SMTP(587/465 등)가 차단됩니다. "
            "증상: smtp.gmail.com 연결 Timeout / unreachable. "
            "대안: Resend·SendGrid 등 HTTPS API로 발송하거나 Pro+ 플랜에서 SMTP 사용. "
            "https://docs.railway.com/reference/outbound-networking#email-delivery"
        )


def send_verification_email(to_addr: str, verify_url: str) -> None:
    if not smtp_verification_enabled():
        raise RuntimeError("SMTP is not configured")
    p = _smtp_params()
    if not p["user"] or not p["password"]:
        raise RuntimeError(
            "SMTP_USER와 SMTP_PASSWORD가 필요합니다. Gmail은 전체 주소 + 앱 비밀번호를 넣으세요."
        )
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

    timeout = _smtp_timeout_sec()
    ehlo = _smtp_ehlo_hostname()
    debug = (os.environ.get("SMTP_DEBUG") or "").strip() in ("1", "true", "yes")

    if p["port"] == 465:
        context = ssl.create_default_context()
        with _SMTP_SSL_IPv4(
            p["host"], p["port"], timeout=timeout, context=context, local_hostname=ehlo
        ) as smtp:
            if debug:
                smtp.set_debuglevel(1)
            smtp.login(p["user"], p["password"])
            smtp.send_message(msg)
    else:
        with _SMTP_IPv4(p["host"], p["port"], timeout=timeout, local_hostname=ehlo) as smtp:
            if debug:
                smtp.set_debuglevel(1)
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(p["user"], p["password"])
            smtp.send_message(msg)
