"""Gemini 모델 ID — Google이 구형 이름을 신규 키에 막을 수 있어 한곳에서 관리합니다."""

import os

# https://ai.google.dev/gemini-api/docs/models
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def get_gemini_model_id() -> str:
    m = (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    return m if m else DEFAULT_GEMINI_MODEL
