"""SE38·개발코드 API/syntax 패턴 KB — 자동 축적·RAG·Admin 후보."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import datetime
from typing import Any

from . import models
from .database import SessionLocal
from .delivered_abap_quality import AbapLintIssue, SE38_SEMANTIC_REVIEW_RULES_KO, lint_se38_semantic_patterns

_log = logging.getLogger(__name__)

ENTRY_CANDIDATE = "candidate"
ENTRY_APPROVED = "approved"
ENTRY_DISMISSED = "dismissed"

SOURCE_LINT_AUTO = "lint_auto"
SOURCE_CODEGEN = "codegen"

# 코드 상수에서 자동 bootstrap (수동 시드 없음)
_LINT_KB_BOOTSTRAP: dict[str, tuple[str, str]] = {
    "param_type_string": (
        "Selection Screen: PARAMETERS TYPE string",
        "Selection Screen의 `PARAMETERS`/`SELECT-OPTIONS`에 **TYPE string** 은 사용할 수 없습니다.\n"
        "- `TYPE c LENGTH n` 또는 텍스트 요소(`TEXT-xxx`)를 사용하세요.",
    ),
    "type_boolean": (
        "ABAP: TYPE boolean 비표준",
        "**TYPE boolean** 은 표준 ABAP 타입이 아닙니다.\n"
        "- `TYPE xfeld`, `TYPE abap_bool`, `TYPE c LENGTH 1` 등을 사용하세요.",
    ),
    "dir_sep_invalid": (
        "cl_abap_char_utilities=>dir_sep 없음",
        "`cl_abap_char_utilities=>dir_sep` 속성은 존재하지 않습니다.\n"
        "- 경로 구분은 `CL_GUI_FRONTEND_SERVICES` 또는 OS별 리터럴/`/` 조합을 사용하세요.",
    ),
    "gui_download_xstring": (
        "GUI_DOWNLOAD: xstring 파라미터 없음",
        "`CALL FUNCTION 'GUI_DOWNLOAD'` 에 **xstring** EXPORTING 파라미터는 없습니다.\n"
        "- `DATA_TAB`(TABLES/CHANGING) + `filename`/`filetype` 등 표준 시그니처를 사용하세요.",
    ),
    "cx_frontend_services": (
        "Classic FM: cx_frontend_services TRY/CATCH",
        "`CL_GUI_FRONTEND_SERVICES` 등 **classic function** 호출에는 "
        "`TRY/CATCH cx_frontend_services` 가 맞지 않습니다.\n"
        "- `sy-subrc` 로 결과를 확인하세요.",
    ),
    "salv_checkbox_type": (
        "ALV SALV: checkbox vs checkbox_hotspot",
        "`if_salv_c_cell_type=>checkbox` 는 클릭이 어렵습니다.\n"
        "- `if_salv_c_cell_type=>checkbox_hotspot` 사용.\n"
        "- checkbox 이벤트가 필요하면 핸들러를 구현하세요.",
    ),
    "pf_status_undefined": (
        "PF-STATUS STANDARD_FULLSCREEN 미정의",
        "`SET_SCREEN_STATUS` / `PF-STATUS 'STANDARD_FULLSCREEN'` 는 "
        "해당 MODULE STATUS에서 정의되지 않으면 활성화 오류가 납니다.\n"
        "- 프로그램에 맞는 PF-STATUS를 MODULE STATUS에서 정의하거나 기존 상태를 사용하세요.",
    ),
    "text_element_duplicate": (
        "Selection Screen TEXT-xxx 중복",
        "동일 **TEXT-xxx** 를 COMMENT와 PUSHBUTTON 등에 중복 사용하면 식별자 충돌이 납니다.\n"
        "- 서로 다른 텍스트 요소 ID를 사용하세요.",
    ),
}

_FM_RE = re.compile(r"(?i)call\s+function\s+['\"]([^'\"]+)['\"]")
_METHOD_RE = re.compile(r"(?i)\b(cl_[a-z0-9_]+)=>([a-z0-9_]+)")
_FORMAL_PARAM_RE = re.compile(
    r'(?i)formal parameter\s+"([^"]+)"\s+does not exist'
)


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())[:120]


def dedupe_key_for_lint(error_code: str) -> str:
    return f"lint:{(error_code or '').strip().lower()}"


def dedupe_key_for_api(api_kind: str, api_name: str) -> str:
    return f"api:{api_kind}:{_norm_key(api_name)}"[:160]


def dedupe_key_for_se38_message(se38_error: str) -> str:
    h = hashlib.sha256(_norm_key(se38_error)[:500].encode("utf-8")).hexdigest()[:24]
    return f"se38:{h}"


def extract_api_refs(se38_error: str = "", source: str = "") -> list[dict[str, str]]:
    text = f"{se38_error}\n{source}"
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _FM_RE.finditer(text):
        name = m.group(1).strip().upper()
        k = f"fm:{name}"
        if k not in seen:
            seen.add(k)
            out.append({"api_kind": "function_module", "api_name": name})
    for m in _METHOD_RE.finditer(text):
        cls = m.group(1).strip().upper()
        meth = m.group(2).strip().upper()
        name = f"{cls}=>{meth}"
        k = f"cl:{name}"
        if k not in seen:
            seen.add(k)
            out.append({"api_kind": "class_method", "api_name": name})
    return out


def _deidentify_sample(text: str, *, max_len: int = 800) -> str:
    t = (text or "").strip()
    t = re.sub(r"(?i)\bZ[A-Z0-9_]{3,}\b", "ZPROGRAM", t)
    t = re.sub(r"(?i)\bY[A-Z0-9_]{3,}\b", "YPROGRAM", t)
    return t[:max_len]


def bootstrap_lint_kb_entries(db) -> int:
    """린트 코드별 approved KB — 수동 시드 없이 코드 상수에서 생성."""
    n = 0
    now = datetime.utcnow()
    for code, (title, body) in _LINT_KB_BOOTSTRAP.items():
        dk = dedupe_key_for_lint(code)
        row = db.query(models.AbapApiKbEntry).filter(models.AbapApiKbEntry.dedupe_key == dk).first()
        if row:
            continue
        db.add(
            models.AbapApiKbEntry(
                dedupe_key=dk,
                entry_status=ENTRY_APPROVED,
                source_kind=SOURCE_LINT_AUTO,
                error_code=code,
                api_kind="pattern",
                api_name=code,
                title_ko=title,
                body_md=body,
                occurrence_count=0,
                approved_at=now,
                last_seen_at=now,
            )
        )
        n += 1
    if n:
        db.commit()
    return n


def _upsert_entry(
    db,
    *,
    dedupe_key: str,
    entry_status: str,
    source_kind: str,
    title_ko: str,
    body_md: str,
    error_code: str | None = None,
    api_kind: str | None = None,
    api_name: str | None = None,
    sample_context: str | None = None,
) -> None:
    now = datetime.utcnow()
    row = db.query(models.AbapApiKbEntry).filter(models.AbapApiKbEntry.dedupe_key == dedupe_key).first()
    if row:
        if row.entry_status == ENTRY_DISMISSED:
            return
        row.occurrence_count = int(row.occurrence_count or 0) + 1
        row.last_seen_at = now
        row.updated_at = now
        if source_kind == SOURCE_CODEGEN and row.source_kind != SOURCE_CODEGEN:
            row.source_kind = SOURCE_CODEGEN
        if sample_context and not (row.sample_context or "").strip():
            row.sample_context = sample_context[:2000]
        if row.entry_status == ENTRY_CANDIDATE and entry_status == ENTRY_APPROVED:
            row.entry_status = ENTRY_APPROVED
            row.approved_at = now
        return
    db.add(
        models.AbapApiKbEntry(
            dedupe_key=dedupe_key,
            entry_status=entry_status,
            source_kind=source_kind,
            error_code=error_code,
            api_kind=api_kind,
            api_name=api_name,
            title_ko=title_ko[:512],
            body_md=body_md,
            sample_context=(sample_context or "")[:2000] or None,
            occurrence_count=1,
            last_seen_at=now,
            approved_at=now if entry_status == ENTRY_APPROVED else None,
        )
    )


def accumulate_from_lint_issues(issues: list[AbapLintIssue]) -> None:
    db = SessionLocal()
    try:
        bootstrap_lint_kb_entries(db)
        for iss in issues:
            code = (iss.code or "").strip()
            if not code:
                continue
            boot = _LINT_KB_BOOTSTRAP.get(code)
            if boot:
                title, body = boot
            else:
                title = f"Lint: {code}"
                body = iss.message_ko or code
            _upsert_entry(
                db,
                dedupe_key=dedupe_key_for_lint(code),
                entry_status=ENTRY_APPROVED,
                source_kind=SOURCE_CODEGEN,
                title_ko=title,
                body_md=body,
                error_code=code,
                api_kind="pattern",
                api_name=code,
            )
        db.commit()
    except Exception:
        _log.exception("[AbapApiKb] lint accumulate failed")
        db.rollback()
    finally:
        db.close()


def schedule_accumulate_from_lint_issues(issues: list[AbapLintIssue]) -> None:
    if not issues:
        return
    threading.Thread(
        target=accumulate_from_lint_issues,
        args=(issues,),
        daemon=True,
        name="abap-api-kb-lint",
    ).start()


def lookup_rag_entries(
    db,
    *,
    se38_error: str = "",
    source: str = "",
    limit: int = 8,
) -> list[models.AbapApiKbEntry]:
    bootstrap_lint_kb_entries(db)
    keys: list[str] = []
    err = (se38_error or "").strip()
    scan_text = f"{err}\n{source or ''}".lower()
    for code in _LINT_KB_BOOTSTRAP:
        if code in scan_text or code.replace("_", " ") in scan_text:
            keys.append(dedupe_key_for_lint(code))
    if (source or "").strip():
        for iss in lint_se38_semantic_patterns(source):
            if iss.code:
                keys.append(dedupe_key_for_lint(iss.code))
    for api in extract_api_refs(err, source):
        keys.append(dedupe_key_for_api(api["api_kind"], api["api_name"]))
    if err:
        keys.append(dedupe_key_for_se38_message(err))

    rows: list[models.AbapApiKbEntry] = []
    seen: set[int] = set()
    if keys:
        for row in (
            db.query(models.AbapApiKbEntry)
            .filter(
                models.AbapApiKbEntry.dedupe_key.in_(keys),
                models.AbapApiKbEntry.entry_status == ENTRY_APPROVED,
            )
            .all()
        ):
            if row.id not in seen:
                seen.add(row.id)
                rows.append(row)

    if len(rows) < limit:
        q = (
            db.query(models.AbapApiKbEntry)
            .filter(models.AbapApiKbEntry.entry_status == ENTRY_APPROVED)
            .order_by(models.AbapApiKbEntry.occurrence_count.desc())
        )
        for api in extract_api_refs(err, source):
            if api["api_name"]:
                extra = (
                    q.filter(models.AbapApiKbEntry.api_name.ilike(f"%{api['api_name'][:40]}%"))
                    .limit(3)
                    .all()
                )
                for row in extra:
                    if row.id not in seen:
                        seen.add(row.id)
                        rows.append(row)
                        if len(rows) >= limit:
                            break
            if len(rows) >= limit:
                break

    return rows[:limit]


def combined_source_from_package(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    parts: list[str] = []
    for sl in data.get("slots") or []:
        if isinstance(sl, dict):
            parts.append(str(sl.get("source") or ""))
    return "\n".join(parts)


def lookup_rag_block_for_sources(
    *,
    se38_error: str = "",
    source: str = "",
    limit: int = 8,
) -> str:
    db = SessionLocal()
    try:
        return format_rag_block(
            lookup_rag_entries(db, se38_error=se38_error, source=source, limit=limit)
        )
    finally:
        db.close()


def format_rag_block(entries: list[models.AbapApiKbEntry]) -> str:
    if not entries:
        return ""
    parts = [
        "## Dev code API/syntax KB (승인됨 — 추측보다 우선)",
        "아래는 플랫폼에 축적된 패턴입니다. **KB와 충돌하면 KB를 따르세요.**",
        "",
    ]
    for row in entries:
        parts.append(f"### {row.title_ko}")
        if row.api_name:
            parts.append(f"- API: `{row.api_name}` (code={row.error_code or '—'})")
        parts.append((row.body_md or "").strip())
        parts.append("")
    parts.append(SE38_SEMANTIC_REVIEW_RULES_KO.strip())
    return "\n".join(parts).strip()


def list_admin_entries(db, *, status: str | None = None) -> list[models.AbapApiKbEntry]:
    q = db.query(models.AbapApiKbEntry).order_by(
        models.AbapApiKbEntry.last_seen_at.desc(),
        models.AbapApiKbEntry.id.desc(),
    )
    if status:
        q = q.filter(models.AbapApiKbEntry.entry_status == status)
    return q.limit(500).all()


def approve_entry(db, entry_id: int, admin_user_id: int) -> bool:
    row = db.query(models.AbapApiKbEntry).filter(models.AbapApiKbEntry.id == entry_id).first()
    if not row or row.entry_status == ENTRY_DISMISSED:
        return False
    now = datetime.utcnow()
    row.entry_status = ENTRY_APPROVED
    row.approved_at = now
    row.approved_by_user_id = int(admin_user_id)
    row.updated_at = now
    db.commit()
    return True


def dismiss_entry(db, entry_id: int) -> bool:
    row = db.query(models.AbapApiKbEntry).filter(models.AbapApiKbEntry.id == entry_id).first()
    if not row:
        return False
    row.entry_status = ENTRY_DISMISSED
    row.updated_at = datetime.utcnow()
    db.commit()
    return True
