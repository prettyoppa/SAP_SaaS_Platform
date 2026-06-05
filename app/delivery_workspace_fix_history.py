"""SE38 작업실 — 슬롯별 AI 수정 제안 이력(동일 제안 반복 방지)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

WORKSPACE_FIX_HISTORY_KEY = "_workspace_fix_history"
_MAX_ENTRIES = 32
_MAX_ERR_STORE = 2_000
_PREVIEW_CHARS = 280


def _norm_err(err: str) -> str:
    return re.sub(r"\s+", " ", (err or "").strip().lower())[:500]


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:20]


def get_fix_history(pkg: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not pkg or not isinstance(pkg, dict):
        return []
    raw = pkg.get(WORKSPACE_FIX_HISTORY_KEY)
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _history_for_slot(history: list[dict[str, Any]], slot_index: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in history:
        try:
            if int(row.get("slot_index", -1)) == int(slot_index):
                out.append(row)
        except (TypeError, ValueError):
            continue
    return out


def append_fix_history(
    pkg: dict[str, Any],
    *,
    slot_index: int,
    se38_error: str,
    source_before: str,
    suggested: str,
) -> None:
    hist = get_fix_history(pkg)
    entry = {
        "slot_index": int(slot_index),
        "se38_error": (se38_error or "")[:_MAX_ERR_STORE],
        "se38_error_norm": _norm_err(se38_error),
        "source_hash": _hash_text(source_before),
        "suggested_hash": _hash_text(suggested),
        "suggested_preview": (suggested or "")[:_PREVIEW_CHARS],
        "at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    hist.append(entry)
    if len(hist) > _MAX_ENTRIES:
        hist = hist[-_MAX_ENTRIES:]
    pkg[WORKSPACE_FIX_HISTORY_KEY] = hist


def suggestion_already_attempted(
    history: list[dict[str, Any]],
    *,
    slot_index: int,
    suggested: str,
    se38_error: str,
) -> bool:
    sug_hash = _hash_text(suggested)
    err_norm = _norm_err(se38_error)
    for row in _history_for_slot(history, slot_index):
        if row.get("suggested_hash") == sug_hash:
            prev_err = (row.get("se38_error_norm") or _norm_err(row.get("se38_error") or "")).strip()
            if not err_norm or not prev_err or err_norm == prev_err or err_norm in prev_err or prev_err in err_norm:
                return True
    return False


def format_fix_history_for_prompt(
    history: list[dict[str, Any]],
    *,
    slot_index: int,
    se38_error: str,
    max_items: int = 6,
) -> str:
    rows = _history_for_slot(history, slot_index)
    if not rows:
        return ""
    err_norm = _norm_err(se38_error)
    relevant = [
        r
        for r in rows
        if not err_norm
        or (r.get("se38_error_norm") or "") == err_norm
        or err_norm in (r.get("se38_error_norm") or "")
        or (r.get("se38_error_norm") or "") in err_norm
    ]
    if not relevant:
        relevant = rows[-max_items:]
    else:
        relevant = relevant[-max_items:]
    lines = [
        "## 이전 AI 수정 시도 (같은 요청·슬롯 — **동일 패치 재출력 금지**)",
        "컨설턴트가 아래 제안을 이미 반영했거나 SE38에서도 시도했을 수 있습니다. **다른 원인·다른 수정**을 제시하세요.",
        "",
    ]
    for i, row in enumerate(relevant, 1):
        when = (row.get("at") or "").strip() or "?"
        err_snip = ((row.get("se38_error") or "").strip().replace("\n", " "))[:160]
        prev = (row.get("suggested_preview") or "").strip().replace("\n", " ")
        if len(prev) > 200:
            prev = prev[:197] + "…"
        lines.append(f"{i}. [{when}] SE38: {err_snip or '—'}")
        if prev:
            lines.append(f"   제안 요약: {prev}")
    lines.append("")
    return "\n".join(lines)
