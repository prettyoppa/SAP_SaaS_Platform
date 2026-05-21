"""Gemini 비전 — 이미지 바이트 목록을 텍스트 요약으로 변환."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ALLOWED_IMAGE_MIME = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
MAX_VISION_IMAGES_DEFAULT = 12
MIN_IMAGE_BYTES = 4_096
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def vision_summarize_images(
    images: list[tuple[bytes, str]],
    *,
    max_chars: int = 8000,
    context_prompt: str | None = None,
    header: str = "",
) -> str:
    """
    images: (raw bytes, filename hint) 목록.
    실패·키 없음 시 빈 문자열 또는 짧은 안내.
    """
    if not images:
        return ""
    loaded: list[tuple[bytes, str, str]] = []
    for raw, fname in images:
        if not raw or len(raw) < MIN_IMAGE_BYTES or len(raw) > MAX_IMAGE_BYTES:
            continue
        fn = (fname or "image.png").strip()
        mime = mimetypes.guess_type(fn)[0] or "image/png"
        if mime not in ALLOWED_IMAGE_MIME:
            if fn.lower().endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            elif fn.lower().endswith(".webp"):
                mime = "image/webp"
            elif fn.lower().endswith(".gif"):
                mime = "image/gif"
            else:
                mime = "image/png"
        loaded.append((raw, fn, mime))
        if len(loaded) >= MAX_VISION_IMAGES_DEFAULT:
            break
    if not loaded:
        return ""

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        names = ", ".join(x[1] for x in loaded[:8])
        return (
            f"{header}[이미지 {len(loaded)}장: {names} — "
            "GOOGLE_API_KEY 없음, 시각 요약 생략]"
        ).strip()

    try:
        import google.generativeai as genai
    except Exception:
        return ""

    from .gemini_model import get_gemini_model_id

    default_prompt = """아래 이미지는 SAP 개발 요청·기능명세(FS)·제안서 첨부에서 추출한 화면·표·다이어그램이다.
각 이미지에서 읽을 수 있는 업무 요구·화면 레이아웃·필드명·표 헤더·에러 메시지를 한국어로 요약하라.
추측으로 없는 기능을 만들지 말고, 보이는 내용과 전달 의도만 정리하라.
출력은 평문만 (제목·불릿 가능). JSON·코드블록 금지."""

    parts: list[Any] = [context_prompt or default_prompt]
    for i, (raw, fname, mime) in enumerate(loaded, 1):
        parts.append(f"\n[이미지 {i}: {fname}]")
        parts.append({"mime_type": mime, "data": raw})

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(get_gemini_model_id())
        resp = model.generate_content(
            parts,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=2048,
                temperature=0.2,
            ),
        )
        text = (getattr(resp, "text", None) or "").strip()
    except Exception:
        return ""

    if not text:
        return ""
    hdr = header or f"[첨부 이미지 {len(loaded)}장 — AI 시각 요약]\n"
    body = text[: max(200, max_chars - len(hdr))]
    return (hdr + body).strip()
