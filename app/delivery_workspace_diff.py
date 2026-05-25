"""SE38 납품 작업실 — 작업본 vs AI 제안 라인 diff (표시용)."""

from __future__ import annotations

import difflib
import html
from typing import Any, Literal

DiffKind = Literal["equal", "delete", "insert", "gap"]

_MAX_LINES = 2400
_COLLAPSE_MIN = 10
_COLLAPSE_CTX = 3


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return text.splitlines()


def compute_line_diff_rows(
    original: str,
    suggested: str,
    *,
    max_rows: int = _MAX_LINES,
) -> list[dict[str, Any]]:
    a = _split_lines(original)
    b = _split_lines(suggested)
    if len(a) + len(b) > max_rows * 2:
        return [
            {
                "kind": "gap",
                "text": f"… diff omitted (>{max_rows} lines). Compare in the editors above.",
                "old_no": None,
                "new_no": None,
            }
        ]
    rows: list[dict[str, Any]] = []
    sm = difflib.SequenceMatcher(None, a, b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k, line in enumerate(a[i1:i2]):
                rows.append(
                    {
                        "kind": "equal",
                        "text": line,
                        "old_no": i1 + k + 1,
                        "new_no": j1 + k + 1,
                    }
                )
        elif tag == "replace":
            for k, line in enumerate(a[i1:i2]):
                rows.append(
                    {
                        "kind": "delete",
                        "text": line,
                        "old_no": i1 + k + 1,
                        "new_no": None,
                    }
                )
            for k, line in enumerate(b[j1:j2]):
                rows.append(
                    {
                        "kind": "insert",
                        "text": line,
                        "old_no": None,
                        "new_no": j1 + k + 1,
                    }
                )
        elif tag == "delete":
            for k, line in enumerate(a[i1:i2]):
                rows.append(
                    {
                        "kind": "delete",
                        "text": line,
                        "old_no": i1 + k + 1,
                        "new_no": None,
                    }
                )
        elif tag == "insert":
            for k, line in enumerate(b[j1:j2]):
                rows.append(
                    {
                        "kind": "insert",
                        "text": line,
                        "old_no": None,
                        "new_no": j1 + k + 1,
                    }
                )
    return rows


def collapse_diff_rows(
    rows: list[dict[str, Any]],
    *,
    min_unchanged: int = _COLLAPSE_MIN,
    context: int = _COLLAPSE_CTX,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    out: list[dict[str, Any]] = []
    i = 0
    n = len(rows)
    while i < n:
        if rows[i].get("kind") != "equal":
            out.append(rows[i])
            i += 1
            continue
        j = i
        while j < n and rows[j].get("kind") == "equal":
            j += 1
        run = rows[i:j]
        if len(run) <= min_unchanged:
            out.extend(run)
        else:
            out.extend(run[:context])
            skipped = len(run) - 2 * context
            out.append(
                {
                    "kind": "gap",
                    "text": f"… {skipped} unchanged lines …",
                    "old_no": None,
                    "new_no": None,
                }
            )
            out.extend(run[-context:])
        i = j
    return out


def render_diff_html(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        kind = row.get("kind") or "equal"
        text = row.get("text") or ""
        old_no = row.get("old_no")
        new_no = row.get("new_no")
        esc = html.escape(text)
        if kind == "gap":
            parts.append(
                f'<div class="dw-diff-line dw-diff-line--gap">'
                f'<span class="dw-diff-gutter">·</span>'
                f'<span class="dw-diff-lnum"></span>'
                f'<span class="dw-diff-code">{esc}</span></div>'
            )
            continue
        gutter = {"equal": " ", "delete": "−", "insert": "+"}.get(kind, " ")
        cls = f"dw-diff-line dw-diff-line--{kind}"
        old_s = str(old_no) if old_no is not None else ""
        new_s = str(new_no) if new_no is not None else ""
        lnum = f'<span class="dw-diff-lnum-old">{html.escape(old_s)}</span>'
        lnum += f'<span class="dw-diff-lnum-new">{html.escape(new_s)}</span>'
        parts.append(
            f'<div class="{cls}">'
            f'<span class="dw-diff-gutter">{gutter}</span>'
            f"{lnum}"
            f'<span class="dw-diff-code">{esc or " "}</span></div>'
        )
    return "\n".join(parts)


def diff_panel_html(original: str, suggested: str) -> str:
    rows = collapse_diff_rows(compute_line_diff_rows(original, suggested))
    return render_diff_html(rows)
