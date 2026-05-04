"""코드 갤러리(admin) — 로컬 텍스트·ABAP 파일 ZIP/다중 업로드 일괄 등록."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from . import sap_fields

MAX_BULK_FILES = 150
MAX_BULK_ZIP_BYTES = 35 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024
MIN_SOURCE_CHARS = 50

_ALLOWED_SUFFIX = frozenset({".txt", ".abap"})


def _pid_error_message(err: str) -> str:
    return {
        "required": "파일명에서 프로그램 ID를 읽을 수 없습니다.",
        "too_long": "프로그램 ID(파일명)가 40자를 초과합니다.",
        "no_ime_chars": "프로그램 ID(파일명)에 한글 등은 사용할 수 없습니다.",
        "invalid_chars": "프로그램 ID(파일명)에 허용되지 않는 문자가 있습니다.",
    }.get(err, "프로그램 ID가 올바르지 않습니다.")


def program_id_from_leaf_filename(leaf: str) -> tuple[str | None, str | None]:
    """
    ZIP/멀티파트의 파일명만 사용. 확장자 .txt / .abap 제거 후 검증.
    확장자 없음: 전체 stem을 프로그램 ID로 시도.
    Returns (normalized_program_id_upper, None) or (None, user_message).
    """
    base = Path(leaf).name
    if not base or base.startswith("."):
        return None, "숨김·빈 파일명은 건너뜁니다."
    suf = Path(base).suffix.lower()
    if suf and suf not in _ALLOWED_SUFFIX:
        return None, f"지원 확장자가 아닙니다(.txt, .abap만): {base}"
    stem = Path(base).stem if suf else base
    stem = stem.strip()
    pid, err = sap_fields.validate_program_id(stem, required=True)
    if err:
        return None, f"{base}: {_pid_error_message(err)}"
    return pid, None


def decode_text_file(raw: bytes) -> tuple[str | None, str | None]:
    if len(raw) > MAX_SINGLE_FILE_BYTES:
        return None, f"파일당 최대 {MAX_SINGLE_FILE_BYTES // (1024 * 1024)}MB까지입니다."
    if not raw.strip():
        return None, "내용이 비어 있습니다."
    for enc in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            return raw.decode(enc), None
        except UnicodeDecodeError:
            continue
    return None, "텍스트 인코딩을 해석하지 못했습니다."


def collect_from_zip(data: bytes) -> tuple[list[dict], list[str]]:
    """
    Returns (items, skip_messages).
    Each item: { "program_id", "source_code", "display_name" }.
    """
    skips: list[str] = []
    if len(data) > MAX_BULK_ZIP_BYTES:
        return [], [f"ZIP 크기는 최대 {MAX_BULK_ZIP_BYTES // (1024 * 1024)}MB까지입니다."]
    items: list[dict] = []
    seen: dict[str, int] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile:
        return [], ["ZIP 파일 형식이 올바르지 않습니다."]
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if "__MACOSX/" in name or "/__MACOSX/" in name:
                continue
            leaf = name.rsplit("/", 1)[-1]
            if not leaf or leaf.startswith("."):
                continue
            pid, err = program_id_from_leaf_filename(leaf)
            if err or not pid:
                skips.append(f"{leaf}: {err or '건너뜀'}")
                continue
            try:
                raw = zf.read(info)
            except Exception as e:
                skips.append(f"{leaf}: 읽기 오류 ({e})")
                continue
            text, derr = decode_text_file(raw)
            if derr or text is None:
                skips.append(f"{leaf}: {derr or '디코딩 실패'}")
                continue
            if len(text.strip()) < MIN_SOURCE_CHARS:
                skips.append(f"{leaf}: ABAP 소스가 너무 짧습니다(최소 {MIN_SOURCE_CHARS}자).")
                continue
            if pid in seen:
                items[seen[pid]] = {
                    "program_id": pid,
                    "source_code": text,
                    "display_name": leaf,
                }
                skips.append(f"{leaf}: 동일 프로그램 ID({pid}) 중복 — 마지막 파일로 덮어씁니다.")
                continue
            seen[pid] = len(items)
            items.append({"program_id": pid, "source_code": text, "display_name": leaf})
            if len(items) >= MAX_BULK_FILES:
                skips.append(f"파일 수 상한({MAX_BULK_FILES}건)에 도달하여 이후 항목은 생략합니다.")
                break
    return items, skips


def collect_from_multipart_files(
    named_bytes: list[tuple[str, bytes]],
) -> tuple[list[dict], list[str]]:
    skips: list[str] = []
    items: list[dict] = []
    seen: dict[str, int] = {}
    for orig_name, raw in named_bytes:
        leaf = Path(orig_name).name
        pid, err = program_id_from_leaf_filename(leaf)
        if err or not pid:
            skips.append(f"{leaf}: {err or '건너뜀'}")
            continue
        text, derr = decode_text_file(raw)
        if derr or text is None:
            skips.append(f"{leaf}: {derr or '디코딩 실패'}")
            continue
        if len(text.strip()) < MIN_SOURCE_CHARS:
            skips.append(f"{leaf}: ABAP 소스가 너무 짧습니다(최소 {MIN_SOURCE_CHARS}자).")
            continue
        if pid in seen:
            items[seen[pid]] = {
                "program_id": pid,
                "source_code": text,
                "display_name": leaf,
            }
            skips.append(f"{leaf}: 동일 프로그램 ID({pid}) 중복 — 마지막 파일로 덮어씁니다.")
            continue
        seen[pid] = len(items)
        items.append({"program_id": pid, "source_code": text, "display_name": leaf})
        if len(items) >= MAX_BULK_FILES:
            skips.append(f"파일 수 상한({MAX_BULK_FILES}건)에 도달하여 이후 항목은 생략합니다.")
            break
    return items, skips
