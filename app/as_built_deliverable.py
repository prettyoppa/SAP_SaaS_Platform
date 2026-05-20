"""최종 구현 산출물(ZIP) — 저장·다운로드·LLM 컨텍스트 추출."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import zipfile
from datetime import datetime
from typing import Any

from . import r2_storage
from .attachment_context import _one_file_digest

# 요청 폼 첨부(ALLOWED_EXTENSIONS)와 동일 + 단일 파일
AS_BUILT_ALLOWED_EXTENSIONS = frozenset({
    ".pdf", ".xlsx", ".xls", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".zip",
})
MAX_AS_BUILT_ZIP_BYTES = 50 * 1024 * 1024
MAX_AS_BUILT_OTHER_BYTES = 20 * 1024 * 1024
MAX_ZIP_FILES_FOR_DIGEST = 120
MAX_ZIP_FILE_BYTES = 2 * 1024 * 1024

_CODE_TEXT_EXT = frozenset({
    ".txt", ".csv", ".tsv", ".log", ".md", ".json", ".xml", ".yml", ".yaml", ".sql", ".ini",
    ".properties", ".abap", ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".bat", ".ps1", ".cmd",
    ".vbs", ".vba", ".cls", ".bas", ".frm", ".vb", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".r", ".m",
    ".swift", ".scala", ".clj", ".lua", ".pl", ".pm", ".rkt", ".dart", ".zig", ".toml",
    ".cfg", ".conf", ".env", ".example", ".sample", ".gradle", ".groovy", ".dockerfile",
    ".makefile", ".cmake", ".proto", ".graphql", ".wsdl", ".xsl", ".xslt",
})


def parse_as_built_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("path"):
        return None
    return data


def as_built_entry(entity: Any) -> dict[str, Any] | None:
    return parse_as_built_json(getattr(entity, "as_built_zip_json", None))


def set_as_built_entry(entity: Any, *, path: str, filename: str) -> None:
    entity.as_built_zip_json = json.dumps(
        {
            "path": path,
            "filename": (filename or "as-built.zip").strip() or "as-built.zip",
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
        },
        ensure_ascii=False,
    )


def clear_as_built_entry(entity: Any) -> None:
    ent = as_built_entry(entity)
    if ent:
        _remove_stored(ent.get("path"))
    entity.as_built_zip_json = None


def store_as_built_file(user_id: int, data: bytes, original_filename: str) -> tuple[str, str]:
    if not data:
        raise ValueError("empty_file")
    fname = (original_filename or "file").strip() or "file"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in AS_BUILT_ALLOWED_EXTENSIONS:
        raise ValueError("invalid_file")
    limit = MAX_AS_BUILT_ZIP_BYTES if ext == ".zip" else MAX_AS_BUILT_OTHER_BYTES
    if len(data) > limit:
        raise ValueError("file_too_large")
    if ext == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                if not any(not i.is_dir() for i in zf.infolist()):
                    raise ValueError("empty_zip")
        except zipfile.BadZipFile as e:
            raise ValueError("invalid_zip") from e

    ct = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    if r2_storage.is_configured():
        uri = r2_storage.upload_bytes(user_id, ext, data, ct)
        return uri, fname
    upload_dir = (
        "/tmp/sap_uploads"
        if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
        else "uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)
    safe = f"asbuilt_{user_id}_{int(datetime.utcnow().timestamp())}{ext}"
    dest = os.path.join(upload_dir, safe)
    with open(dest, "wb") as f:
        f.write(data)
    return dest, fname


def _remove_stored(path: str | None) -> None:
    if not path:
        return
    r2_storage.delete_if_r2_uri(path)
    if path.startswith(r2_storage.R2_PREFIX):
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def digest_zip_archive(raw: bytes, *, max_total_chars: int = 24_000) -> str:
    """ZIP 내부 텍스트·코드 파일을 LLM용 문자열로 추출."""
    if len(raw) > MAX_AS_BUILT_ZIP_BYTES:
        return "(ZIP이 허용 크기를 초과합니다.)"
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile:
        return "(ZIP 형식이 올바르지 않습니다.)"

    parts: list[str] = ["(ZIP 아카이브 내부 추출)"]
    used = 0
    file_count = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if "__MACOSX/" in name or name.startswith("."):
                continue
            leaf = name.rsplit("/", 1)[-1]
            if not leaf:
                continue
            if file_count >= MAX_ZIP_FILES_FOR_DIGEST:
                parts.append("…(ZIP 내 파일 수 상한 — 이후 생략)")
                break
            try:
                file_raw = zf.read(info)
            except Exception as e:
                parts.append(f"[{name}] 읽기 오류: {e}")
                file_count += 1
                continue
            if len(file_raw) > MAX_ZIP_FILE_BYTES:
                parts.append(f"[{name}] 파일 크기 상한({MAX_ZIP_FILE_BYTES // (1024*1024)}MB) 초과 — 생략")
                file_count += 1
                continue
            ext = os.path.splitext(leaf)[1].lower()
            per_budget = max(800, (max_total_chars - used) // max(1, MAX_ZIP_FILES_FOR_DIGEST - file_count))
            if ext in _CODE_TEXT_EXT or ext == "":
                block = _one_file_digest(name, file_raw, per_budget)
            elif ext in (".pdf", ".xlsx", ".xlsm", ".xls"):
                block = _one_file_digest(leaf, file_raw, per_budget)
            else:
                block = f"[{name}] 바이너리/미지원 확장자 — 파일명·경로만 참고"
            if used + len(block) > max_total_chars:
                block = block[: max(200, max_total_chars - used)] + "\n…"
            parts.append(block)
            used += len(block)
            file_count += 1
            if used >= max_total_chars:
                break
    text = "\n\n".join(parts).strip()
    if len(text) > max_total_chars:
        text = text[:max_total_chars] + "\n…(ZIP 컨텍스트 상한)…"
    return text


def as_built_hub_template_ctx(
    entity: Any,
    *,
    user: Any,
    db: Any,
    request_kind: str,
    return_to: str,
) -> dict[str, Any]:
    from .request_hub_access import consultant_is_matched_on_request

    can_upload = False
    if user and entity:
        if getattr(user, "is_admin", False):
            can_upload = True
        elif int(getattr(user, "id", 0)) == int(getattr(entity, "user_id", 0)):
            can_upload = True
        elif getattr(user, "is_consultant", False):
            can_upload = consultant_is_matched_on_request(
                db,
                consultant_user_id=int(user.id),
                request_kind=request_kind,
                request_id=int(entity.id),
            )
    ent = as_built_entry(entity) or {}
    return {
        "as_built_entity": entity,
        "as_built_request_kind": request_kind,
        "as_built_entry_dict": ent,
        "as_built_can_upload": can_upload,
        "as_built_return_to": return_to,
    }


def as_built_llm_digest(entity: Any, *, max_total_chars: int = 10_000) -> str:
    ent = as_built_entry(entity)
    if not ent:
        return ""
    raw = r2_storage.read_bytes_from_ref(ent.get("path") or "")
    if not raw:
        return ""
    fname = (ent.get("filename") or "file").strip()
    head = f"[최종 구현 산출물: {fname}]\n"
    budget = max(1000, max_total_chars - len(head))
    ext = os.path.splitext(fname)[1].lower()
    if ext == ".zip":
        body = digest_zip_archive(raw, max_total_chars=budget)
    else:
        body = _one_file_digest(fname, raw, budget)
    return (head + body).strip()[:max_total_chars]


def store_as_built_zip(user_id: int, data: bytes, original_filename: str) -> tuple[str, str]:
    """레거시 별칭."""
    return store_as_built_file(user_id, data, original_filename)
