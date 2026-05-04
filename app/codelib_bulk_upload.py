"""코드 갤러리(admin) — ZIP/다중 파일 일괄 등록(프로그램별 묶음·섹션)."""

from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import sap_fields

# ZIP·멀티파트 전체 바이트 상한(라우터와 동일 기준)
MAX_BULK_ZIP_BYTES = 35 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024
# 입력 파일(Include 등) 개수 상한
MAX_INPUT_FILES = 350
# 생성되는 갤러리 프로그램(ABAPCode 행) 개수 상한
MAX_OUTPUT_PROGRAMS = 120
# 한 프로그램에 합칠 수 있는 최대 파일(섹션) 수
MAX_SECTIONS_PER_PROGRAM = 64
# 묶인 전체 소스 최소 길이(단건 업로드와 동일하게 너무 짧은 건 제외)
MIN_COMBINED_CHARS = 50

_ALLOWED_EXT = frozenset({".txt", ".abap", ".docx"})
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 업로드 폼·역파서와 동일: 유형 – 이름 (U+2013)
_LABEL_EN_DASH = "\u2013"


def _pid_error_message(err: str) -> str:
    return {
        "required": "파일명에서 프로그램 ID를 읽을 수 없습니다.",
        "too_long": "프로그램 ID(파일명)가 40자를 초과합니다.",
        "no_ime_chars": "프로그램 ID(파일명)에 한글 등은 사용할 수 없습니다.",
        "invalid_chars": "프로그램 ID(파일명)에 허용되지 않는 문자가 있습니다.",
    }.get(err, "프로그램 ID가 올바르지 않습니다.")


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


def text_from_docx_bytes(raw: bytes) -> tuple[str | None, str | None]:
    """Word OOXML에서 본문 텍스트만 추출(외부 라이브러리 없음)."""
    if len(raw) > MAX_SINGLE_FILE_BYTES:
        return None, f"파일당 최대 {MAX_SINGLE_FILE_BYTES // (1024 * 1024)}MB까지입니다."
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        if "word/document.xml" not in zf.namelist():
            return None, "DOCX가 아닙니다."
        root = ET.fromstring(zf.read("word/document.xml"))
    except zipfile.BadZipFile:
        return None, "DOCX(ZIP) 형식이 아닙니다."
    except Exception as e:
        return None, f"DOCX 읽기 오류: {e}"

    lines: list[str] = []
    for p in root.iter(f"{_W_NS}p"):
        chunks: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W_NS}t" and node.text:
                chunks.append(node.text)
        line = "".join(chunks).rstrip("\n")
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        return None, "DOCX에서 추출한 텍스트가 비어 있습니다."
    return text, None


def _decode_leaf_bytes(leaf: str, raw: bytes) -> tuple[str | None, str | None]:
    ext = Path(leaf).suffix.lower()
    if ext == ".docx":
        return text_from_docx_bytes(raw)
    return decode_text_file(raw)


def _base_program_id_from_stem(stem: str) -> tuple[str | None, str | None]:
    """
    파일명 stem에서 그룹 기준 프로그램 ID.
    첫 '_' 앞을 메인 프로그램 ID로 사용 (ZLSDF64170_CLS → ZLSDF64170).
    '_' 없으면 stem 전체가 프로그램 ID.
    """
    s = stem.strip()
    if not s:
        return None, "빈 파일명입니다."
    if "_" in s:
        head, _tail = s.split("_", 1)
        base_raw = head.strip()
    else:
        base_raw = s
    pid, err = sap_fields.validate_program_id(base_raw, required=True)
    if err:
        return None, _pid_error_message(err)
    return pid, None


def _leaf_allowed(leaf: str) -> tuple[str | None, str | None]:
    """Returns (lower extension including dot) or (None, error)."""
    base = Path(leaf).name
    if not base or base.startswith("."):
        return None, "숨김·빈 파일명은 건너뜁니다."
    suf = Path(base).suffix.lower()
    if suf not in _ALLOWED_EXT:
        return None, f"지원 확장자가 아닙니다(.txt, .abap, .docx): {base}"
    return suf, None


def build_codelib_combined_source(section_pairs: list[tuple[str, str]]) -> str:
    """
    codelib_upload.html JS와 동일한 *&==== / *& [n] 메인 프로그램 – 섹션명 블록.
    section_pairs: (섹션 표시명, 코드) 순서대로.
    """
    out: list[str] = []
    for i, (sec_name, code) in enumerate(section_pairs, start=1):
        label = f"메인 프로그램 {_LABEL_EN_DASH} {sec_name}"
        out.append("*&======================================================\n")
        out.append(f"*& [{i}] {label}\n")
        out.append("*&======================================================\n")
        out.append(code.strip() + "\n\n")
    return "".join(out)


def bulk_group_to_program_items(named_raw: list[tuple[str, bytes]]) -> tuple[list[dict], list[str]]:
    """
    (원본 파일명, 바이트) 목록 → 프로그램별 1행(섹션 합친 source_code).

    각 결과 dict:
      program_id, source_code, display_name, section_count, source_leaves
    """
    skips: list[str] = []
    # base_pid -> list of { stem, stem_u, leaf, text }
    groups: dict[str, list[dict]] = {}
    stem_seen: dict[str, set[str]] = {}

    for leaf, raw in named_raw:
        _, ext_err = _leaf_allowed(leaf)
        if ext_err:
            skips.append(f"{Path(leaf).name}: {ext_err}")
            continue
        stem = Path(Path(leaf).name).stem.strip()
        if not stem:
            skips.append(f"{leaf}: 확장자만 있는 파일명은 건너뜁니다.")
            continue
        base_pid, berr = _base_program_id_from_stem(stem)
        if berr or not base_pid:
            skips.append(f"{Path(leaf).name}: {berr or '프로그램 ID 오류'}")
            continue
        text, derr = _decode_leaf_bytes(leaf, raw)
        if derr or text is None:
            skips.append(f"{Path(leaf).name}: {derr or '내용 없음'}")
            continue
        stem_u = stem.upper()
        if base_pid not in stem_seen:
            stem_seen[base_pid] = set()
        if stem_u in stem_seen[base_pid]:
            for row in groups.get(base_pid, []):
                if row["stem_u"] == stem_u:
                    row["text"] = text
                    row["leaf"] = Path(leaf).name
                    break
            skips.append(f"{Path(leaf).name}: 동일 stem({stem_u}) 중복 — 마지막 파일로 덮어씁니다.")
            continue
        stem_seen[base_pid].add(stem_u)
        groups.setdefault(base_pid, []).append({
            "stem": stem,
            "stem_u": stem_u,
            "leaf": Path(leaf).name,
            "text": text,
        })

    items: list[dict] = []
    for base_pid in sorted(groups.keys()):
        rows = groups[base_pid]
        if len(rows) > MAX_SECTIONS_PER_PROGRAM:
            skips.append(
                f"{base_pid}: 파일이 {len(rows)}개로 많아 상위 {MAX_SECTIONS_PER_PROGRAM}개만 사용합니다."
            )
            rows = rows[:MAX_SECTIONS_PER_PROGRAM]

        def _sort_key(r: dict) -> tuple[int, str]:
            # 메인(파일명 stem이 프로그램 ID와 동일)을 먼저
            main_first = 0 if r["stem_u"] == base_pid else 1
            return (main_first, r["stem_u"])

        rows_sorted = sorted(rows, key=_sort_key)
        section_pairs = [(r["stem"], r["text"]) for r in rows_sorted]
        combined = build_codelib_combined_source(section_pairs)
        if len(combined.strip()) < MIN_COMBINED_CHARS:
            skips.append(
                f"{base_pid}: 합친 소스가 너무 짧습니다(최소 {MIN_COMBINED_CHARS}자). "
                f"(파일 {len(rows_sorted)}개)"
            )
            continue
        leaves = [r["leaf"] for r in rows_sorted]
        display = f"{base_pid} · {len(rows_sorted)}파일 → 1건"
        items.append({
            "program_id": base_pid,
            "source_code": combined,
            "display_name": display,
            "section_count": len(rows_sorted),
            "source_leaves": leaves,
        })
        if len(items) >= MAX_OUTPUT_PROGRAMS:
            skips.append(
                f"등록 프로그램 수가 상한({MAX_OUTPUT_PROGRAMS}건)에 도달하여 "
                "이후 그룹은 생략합니다."
            )
            break

    return items, skips


def collect_from_zip(data: bytes) -> tuple[list[dict], list[str]]:
    skips: list[str] = []
    if len(data) > MAX_BULK_ZIP_BYTES:
        return [], [f"ZIP 크기는 최대 {MAX_BULK_ZIP_BYTES // (1024 * 1024)}MB까지입니다."]
    named_raw: list[tuple[str, bytes]] = []
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
            if len(named_raw) >= MAX_INPUT_FILES:
                skips.append(
                    f"ZIP 내 파일이 {MAX_INPUT_FILES}개를 넘어 이후 항목은 생략합니다."
                )
                break
            try:
                raw = zf.read(info)
            except Exception as e:
                skips.append(f"{leaf}: 읽기 오류 ({e})")
                continue
            named_raw.append((leaf, raw))

    items, more = bulk_group_to_program_items(named_raw)
    skips.extend(more)
    return items, skips


def collect_from_multipart_files(
    named_bytes: list[tuple[str, bytes]],
) -> tuple[list[dict], list[str]]:
    skips: list[str] = []
    if len(named_bytes) > MAX_INPUT_FILES:
        skips.append(
            f"선택한 파일이 {MAX_INPUT_FILES}개를 넘습니다. 앞의 {MAX_INPUT_FILES}개만 처리합니다."
        )
        named_bytes = named_bytes[:MAX_INPUT_FILES]
    return bulk_group_to_program_items(named_bytes)
