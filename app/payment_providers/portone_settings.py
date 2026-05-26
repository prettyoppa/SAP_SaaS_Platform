"""PortOne V2 환경 설정."""

from __future__ import annotations

import os

PORTONE_API_SECRET_ENV = "PORTONE_API_SECRET"
PORTONE_STORE_ID_ENV = "PORTONE_STORE_ID"
PORTONE_CHANNEL_KEY_ENV = "PORTONE_CHANNEL_KEY"
PORTONE_WEBHOOK_SECRET_ENV = "PORTONE_WEBHOOK_SECRET"


def portone_api_secret() -> str:
    return (os.environ.get(PORTONE_API_SECRET_ENV) or "").strip()


def portone_store_id() -> str:
    return (os.environ.get(PORTONE_STORE_ID_ENV) or "").strip()


def portone_channel_key() -> str:
    return (os.environ.get(PORTONE_CHANNEL_KEY_ENV) or "").strip()


def portone_webhook_secret() -> str:
    return (os.environ.get(PORTONE_WEBHOOK_SECRET_ENV) or "").strip()


def portone_checkout_ready() -> bool:
    """브라우저 결제창 + 서버 동기화에 필요한 최소 설정."""
    return bool(portone_api_secret() and portone_store_id() and portone_channel_key())


def portone_webhook_ready() -> bool:
    return bool(portone_api_secret() and portone_webhook_secret())
