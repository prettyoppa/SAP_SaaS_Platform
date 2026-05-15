"""요구사항 자유 기술 — 클립보드 캡처(스크린샷) 저장·표시·LLM 비전 요약."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from . import r2_storage

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_SCREENSHOT_COUNT = 5
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024  # 2MB per image
MAX_SCREENSHOT_TOTAL_BYTES = 8 * 1024 * 1024  # 8MB per request
ALLOWED_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

_LOCAL_UPLOAD_DIR = (
    Path(__file__).resolve().parent.parent / "uploads" / "requirement_screenshots"
)


def entries_from_json(raw: Optional[str]) -> list[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and item.get("path"):
            out.append(
                {
                    "path": str(item["path"]),
                    "filename": (item.get("filename") or "screenshot.png").strip()
                    or "screenshot.png",
                    "size": int(item.get("size") or 0),
                }
            )
    return out


def entries_to_json(entries: list[dict[str, Any]]) -> Optional[str]:
    if not entries:
        return None
    return json.dumps(entries, ensure_ascii=False)


def remove_stored_entries(entries: list[dict[str, Any]]) -> None:
    for ent in entries or []:
        path = (ent or {}).get("path")
        if path:
            r2_storage.delete_if_r2_uri(path)
            kind, ref = r2_storage.parse_storage_ref(path)
            if kind == "local" and ref and os.path.isfile(ref):
                try:
                    os.remove(ref)
                except OSError:
                    pass


def duplicate_entries(entries: list[dict[str, Any]], *, user_id: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ent in entries or []:
        path = (ent or {}).get("path")
        fname = (ent.get("filename") or "screenshot.png").strip() or "screenshot.png"
        if not path:
            continue
        raw = r2_storage.read_bytes_from_ref(path)
        if not raw:
            continue
        mime = mimetypes.guess_type(fname)[0] or "image/png"
        stored = _store_bytes(user_id, raw, mime, fname)
        if stored:
            out.append(stored)
    return out


def _store_bytes(user_id: int, data: bytes, mime: str, filename: str) -> Optional[dict[str, Any]]:
    ext = _EXT_BY_MIME.get(mime) or os.path.splitext(filename)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    if r2_storage.is_configured():
        path = r2_storage.upload_bytes(user_id, ext, data, mime)
    else:
        _LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe = f"reqshot_{user_id}_{int(time.time())}_{uuid.uuid4().hex}{ext}"
        dest = _LOCAL_UPLOAD_DIR / safe
        dest.write_bytes(data)
        path = str(dest)
    return {
        "path": path,
        "filename": filename,
        "size": len(data),
    }


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    s = (data_url or "").strip()
    m = re.match(r"^data:(image/[a-z0-9.+-]+);base64,(.+)$", s, re.I | re.S)
    if m:
        mime = m.group(1).lower()
        raw_b64 = m.group(2)
    else:
        mime = "image/png"
        raw_b64 = s
    try:
        data = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError("screenshot_invalid") from exc
    if mime not in ALLOWED_MIME:
        raise ValueError("screenshot_invalid")
    return data, mime


def process_form_state(
    *,
    user_id: int,
    existing_entries: list[dict[str, Any]],
    state_json: str,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    클라이언트 hidden JSON → 저장 엔트리 목록.
    오류 시 (기존 유지용 빈 리스트가 아니라) error_key 반환.
    """
    try:
        state = json.loads(state_json or "{}")
    except Exception:
        return existing_entries, "screenshot_invalid"
    if not isinstance(state, dict):
        return existing_entries, "screenshot_invalid"

    keep_paths = state.get("keep_paths")
    if keep_paths is None:
        keep_paths = [e.get("path") for e in existing_entries if e.get("path")]
    if not isinstance(keep_paths, list):
        return existing_entries, "screenshot_invalid"

    kept: list[dict[str, Any]] = []
    for ent in existing_entries:
        p = ent.get("path")
        if p and p in keep_paths:
            kept.append(ent)

    new_items = state.get("new")
    if new_items is None:
        new_items = []
    if not isinstance(new_items, list):
        return existing_entries, "screenshot_invalid"

    if len(kept) + len(new_items) > MAX_SCREENSHOT_COUNT:
        return existing_entries, "screenshot_too_many"

    total = sum(int(e.get("size") or 0) for e in kept)
    built_new: list[dict[str, Any]] = []

    def _fail(err: str) -> tuple[list[dict[str, Any]], str]:
        if built_new:
            remove_stored_entries(built_new)
        return existing_entries, err

    for i, item in enumerate(new_items):
        if not isinstance(item, dict):
            return _fail("screenshot_invalid")
        data_field = (item.get("data") or "").strip()
        if not data_field:
            continue
        try:
            raw, mime = _decode_data_url(data_field)
        except ValueError as e:
            return _fail(str(e.args[0]) if e.args else "screenshot_invalid")
        if len(raw) > MAX_SCREENSHOT_BYTES:
            return _fail("screenshot_too_large")
        total += len(raw)
        if total > MAX_SCREENSHOT_TOTAL_BYTES:
            return _fail("screenshot_total_too_large")
        name = (item.get("name") or f"screenshot-{len(kept) + len(built_new) + 1}.png").strip()
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            name += _EXT_BY_MIME.get(mime, ".png")
        stored = _store_bytes(user_id, raw, mime, name)
        if not stored:
            return _fail("screenshot_invalid")
        built_new.append(stored)

    final = kept + built_new
    if len(final) > MAX_SCREENSHOT_COUNT:
        return _fail("screenshot_too_many")

    # 삭제된 기존 파일 정리
    kept_paths_set = {e.get("path") for e in kept}
    for ent in existing_entries:
        if ent.get("path") not in kept_paths_set:
            remove_stored_entries([ent])

    return final, None


def build_requirement_screenshots_llm_digest(
    entries: list[dict[str, Any]],
    *,
    max_chars: int = 8000,
) -> str:
    """Gemini 비전으로 캡처 내용을 텍스트 요약(실패 시 빈 문자열)."""
    if not entries:
        return ""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        names = ", ".join((e.get("filename") or "image") for e in entries[:MAX_SCREENSHOT_COUNT])
        return (
            f"[요구사항 캡처 이미지 {len(entries)}장: {names} — "
            "비전 API 키 없음, 텍스트 요약 생략]"
        )

    try:
        import google.generativeai as genai
    except Exception:
        return ""

    from .gemini_model import get_gemini_model_id

    parts: list[Any] = [
        """아래 이미지는 SAP ABAP 분석·개선 요청의 「요구사항 자유 기술」에 붙인 화면 캡처다.
각 이미지에서 읽을 수 있는 업무 요구·화면·표·에러 메시지·필드명을 한국어로 요약하라.
추측으로 없는 기능을 만들지 말고, 보이는 내용과 요청자가 전달하려는 의도만 정리하라.
출력은 평문만 (제목·불릿 가능). JSON·코드블록 금지."""
    ]
    loaded = 0
    for i, ent in enumerate(entries[:MAX_SCREENSHOT_COUNT], 1):
        raw = r2_storage.read_bytes_from_ref(ent.get("path"))
        if not raw:
            continue
        fname = ent.get("filename") or f"screenshot-{i}.png"
        mime = mimetypes.guess_type(fname)[0] or "image/png"
        if mime not in ALLOWED_MIME:
            mime = "image/png"
        parts.append(f"\n[캡처 {i}: {fname}]")
        parts.append({"mime_type": mime, "data": raw})
        loaded += 1
    if loaded == 0:
        return ""

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
    header = f"[요구사항 캡처 이미지 {loaded}장 — AI 시각 요약]\n"
    body = text[: max_chars - len(header)]
    return (header + body).strip()
