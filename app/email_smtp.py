"""
회원 인증 메일 발송.

- Resend HTTPS API: Railway Hobby 등 SMTP 차단 환경용 (RESEND_API_KEY).
- SMTP: Pro+ 등 아웃바운드 SMTP 허용 환경용 (SMTP_HOST + MAIL_FROM).
"""
from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage


def resend_api_enabled() -> bool:
    return bool((os.environ.get("RESEND_API_KEY") or "").strip())


def smtp_verification_enabled() -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    mail_from = (os.environ.get("MAIL_FROM") or "").strip()
    return bool(host and mail_from)


def email_verification_enabled() -> bool:
    """인증 메일 플로우 사용 여부 (Resend 또는 SMTP 중 하나라도 설정되면 True)."""
    return resend_api_enabled() or smtp_verification_enabled()


def _verification_subject_and_body(verify_url: str) -> tuple[str, str]:
    subject = os.environ.get("MAIL_VERIFY_SUBJECT", "[SAP Dev Hub] 이메일 주소를 확인해 주세요")
    body = (
        "아래 링크를 눌러 이메일 인증을 완료해 주세요.\n\n"
        f"{verify_url}\n\n"
        "이 링크는 며칠 동안만 유효합니다. 요청하지 않으셨다면 이 메일을 무시하세요."
    )
    return subject, body


def _resend_from_address() -> str:
    """Resend 발신 주소. 도메인 인증 전에는 onboarding@resend.dev 등 Resend 안내 주소 사용."""
    return (
        (os.environ.get("RESEND_FROM") or "").strip()
        or (os.environ.get("MAIL_FROM") or "").strip()
    )


def _send_via_resend(to_addr: str, subject: str, body: str) -> None:
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    from_addr = _resend_from_address()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY가 없습니다.")
    if not from_addr:
        raise RuntimeError(
            "발신 주소가 필요합니다. Railway Variables에 RESEND_FROM "
            "(또는 Resend에서 허용된 MAIL_FROM)을 설정하세요."
        )

    payload = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": body,
    }
    data = json.dumps(payload).encode("utf-8")
    # Resend/Cloudflare: User-Agent 없으면 403 + error code 1010
    # https://resend.com/docs/knowledge-base/403-error-1010
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": (os.environ.get("RESEND_USER_AGENT") or "SAP-Dev-Hub/1.0 (verification)"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"Resend HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Resend 연결 실패: {e}") from e


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
    기동 시 메일 설정 점검 로그. 비밀번호·API 키 전체는 출력하지 않습니다.
    """
    pub = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    if pub and not (pub.startswith("https://") or pub.startswith("http://")):
        root_logger.error(
            "[Email] PUBLIC_BASE_URL must include scheme, e.g. https://sap.example.com (got: %s)",
            pub[:80],
        )
    elif not pub:
        root_logger.warning(
            "[Email] PUBLIC_BASE_URL is empty; verify links will use request host (set explicitly behind proxies)"
        )

    if resend_api_enabled():
        from_ok = bool(_resend_from_address())
        root_logger.info(
            "[Email] Resend API enabled (api_key set, from_set=%s). Railway Hobby에서 SMTP 대신 사용 가능.",
            from_ok,
        )
        if not from_ok:
            root_logger.error(
                "[Email] Set RESEND_FROM (e.g. onboarding@resend.dev for Resend 테스트) or MAIL_FROM."
            )
        # Resend가 있으면 SMTP는 보조; SMTP만 쓰는 경우의 Railway 경고는 아래에서 처리
    if not email_verification_enabled():
        root_logger.info(
            "[Email] verification disabled (set RESEND_API_KEY or SMTP_HOST+MAIL_FROM)"
        )
        return

    if not resend_api_enabled() and smtp_verification_enabled():
        p = _smtp_params()
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
                "[SMTP] SMTP_USER and SMTP_PASSWORD are required for SMTP — "
                "or use RESEND_API_KEY on Railway Hobby."
            )
        if "gmail" in p["host"].lower() and p["port"] not in (587, 465):
            root_logger.warning("[SMTP] Gmail usually uses port 587 or 465; current port=%s", p["port"])
        root_logger.info(
            "[SMTP] SMTP_FORCE_IPV4=%s (if connect fails with Errno 101, keep enabled)",
            _smtp_force_ipv4(),
        )
        if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
            root_logger.warning(
                "[SMTP] Railway Hobby: outbound SMTP is blocked — prefer Resend (HTTPS). "
                "https://docs.railway.com/reference/outbound-networking#email-delivery"
            )


def _deliver_plain_email(to_addr: str, subject: str, body: str) -> None:
    if resend_api_enabled():
        _send_via_resend(to_addr, subject, body)
        return

    if not smtp_verification_enabled():
        raise RuntimeError(
            "메일 발송 설정이 없습니다. Railway에는 RESEND_API_KEY(+ RESEND_FROM)를 권장합니다."
        )
    p = _smtp_params()
    if not p["user"] or not p["password"]:
        raise RuntimeError(
            "SMTP_USER와 SMTP_PASSWORD가 필요합니다. Gmail은 전체 주소 + 앱 비밀번호를 넣으세요."
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


def send_verification_email(to_addr: str, verify_url: str) -> None:
    subject, body = _verification_subject_and_body(verify_url)
    _deliver_plain_email(to_addr, subject, body)


def send_registration_otp_email(to_addr: str, code: str) -> None:
    try:
        ttl = max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        ttl = 10
    subject = os.environ.get("REGISTRATION_CODE_MAIL_SUBJECT", "[SAP Dev Hub] 이메일 인증 코드")
    body = (
        f"회원가입 인증 코드: {code}\n\n"
        f"이 코드는 약 {ttl}분간 유효합니다. 본인이 요청하지 않았다면 이 메일을 무시하세요."
    )
    _deliver_plain_email(to_addr, subject, body)
