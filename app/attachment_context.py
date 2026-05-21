"""첨부 파일에서 LLM 컨텍스트용 텍스트·이미지 비전 요약."""

from __future__ import annotations

from typing import Any

from . import r2_storage
from .document_llm_digest import document_file_digest
from .requirement_screenshots import build_requirement_screenshots_llm_digest


def _one_file_digest(filename: str, raw: bytes, per_budget: int) -> str:
    return document_file_digest(filename, raw, per_budget)


def build_attachment_llm_digest(
    entries: list[dict[str, Any]],
    *,
    max_total_chars: int = 12_000,
    note: str = "",
) -> str:
    """저장된 첨부 경로에서 바이너리를 읽어 LLM 프롬프트 문자열 생성."""
    if not entries:
        return ""
    budgets = max_total_chars // max(1, len(entries))
    budgets = max(budgets, 1_800)
    parts: list[str] = []
    if note.strip():
        parts.append(note.strip())
    parts.append("(아래는 서버가 저장한 첨부에서 추출·요약했습니다.)")
    for ent in entries:
        path = (ent or {}).get("path") or ""
        fname = ((ent or {}).get("filename") or "file").strip()
        memo = ((ent or {}).get("note") or "").strip()
        raw = r2_storage.read_bytes_from_ref(path)
        if not raw:
            parts.append(f"[{fname}] — 파일 바이너리를 읽지 못했습니다.")
            continue
        hdr = fname
        if memo:
            hdr += f" (메모: {memo})"
        parts.append(hdr)
        ext = __import__("os").path.splitext(fname)[1].lower()
        if ext == ".zip":
            from .as_built_deliverable import digest_zip_archive

            parts.append(f"[{fname} — ZIP 내부 추출]\n{digest_zip_archive(raw, max_total_chars=budgets)}")
        else:
            parts.append(_one_file_digest(fname, raw, budgets))
    text = "\n\n".join(parts)
    if len(text) > max_total_chars:
        text = text[:max_total_chars] + "\n…(첨부 컨텍스트 상한)…"
    return text.strip()


def build_request_context_digest(
    file_entries: list[dict[str, Any]],
    screenshot_entries: list[dict[str, Any]] | None = None,
    *,
    max_total_chars: int = 14_000,
    file_note: str = "",
) -> str:
    """파일 첨부 + 요구사항 캡처(비전)를 하나의 컨텍스트로."""
    parts: list[str] = []
    file_cap = max_total_chars
    if screenshot_entries:
        file_cap = int(max_total_chars * 0.62)
    d_files = build_attachment_llm_digest(
        file_entries or [], max_total_chars=file_cap, note=file_note
    )
    if d_files.strip():
        parts.append(d_files.strip())
    d_shots = build_requirement_screenshots_llm_digest(
        screenshot_entries or [],
        max_chars=max(2000, max_total_chars - len("\n\n".join(parts))),
    )
    if d_shots.strip():
        parts.append(d_shots.strip())
    combined = "\n\n".join(parts)
    if len(combined) > max_total_chars:
        combined = combined[:max_total_chars] + "\n…(요청 컨텍스트 상한)…"
    return combined.strip()
