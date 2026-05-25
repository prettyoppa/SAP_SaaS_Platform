"""SE38 납품 작업실 — AI 제안 ABAP 검증(잘림·구조)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

WarnCode = Literal["source_shorter", "structure_gap", "suspicious_short"]

MAIN_SLOT_ROLES = frozenset({"main_report", "main", "report"})
INCLUDE_LIKE_ROLES = frozenset(
    {"include", "top", "pbo", "pai", "forms", "screen", "sub", "other"}
)

_FIX_ELSEWHERE_RE = re.compile(
    r"(?im)^\s*\*\s*DW-FIX-ELSEWHERE:\s*(.+?)\s*$",
)


@dataclass(frozen=True)
class SuggestionValidation:
    ok: bool
    warn_codes: tuple[str, ...]
    original_lines: int
    suggested_lines: int
    line_ratio: float


def _line_count(text: str) -> int:
    if not (text or "").strip():
        return 0
    return len(text.splitlines())


def _has_report_statement(text: str) -> bool:
    return bool(re.search(r"(?im)^\s*REPORT\s+", text or ""))


def validate_suggested_against_original(
    original: str,
    suggested: str,
    *,
    slot_role: str = "",
) -> SuggestionValidation:
    """
    반영 전 검사. ok=False 이고 warn만 있으면 차단(경고) — force_apply로 우회.
    """
    orig = original or ""
    sug = (suggested or "").strip()
    o_lines = _line_count(orig)
    s_lines = _line_count(sug)
    ratio = (s_lines / o_lines) if o_lines > 0 else (1.0 if s_lines > 0 else 0.0)

    warns: list[str] = []

    if o_lines >= 30 and ratio < 0.55:
        warns.append("source_shorter")
    elif o_lines >= 12 and ratio < 0.45:
        warns.append("source_shorter")
    elif o_lines >= 8 and s_lines < max(3, int(o_lines * 0.35)):
        warns.append("suspicious_short")

    role = (slot_role or "").strip().lower()
    if role in ("main_report", "main", "top") or _has_report_statement(orig):
        if _has_report_statement(orig) and not _has_report_statement(sug) and o_lines >= 15:
            warns.append("structure_gap")

    ok = len(warns) == 0
    return SuggestionValidation(
        ok=ok,
        warn_codes=tuple(warns),
        original_lines=o_lines,
        suggested_lines=s_lines,
        line_ratio=round(ratio, 3),
    )


def slot_is_include_like(role: str) -> bool:
    r = (role or "").strip().lower()
    if r in MAIN_SLOT_ROLES:
        return False
    return r in INCLUDE_LIKE_ROLES or r not in {"doc", "requirements", "env_sample", "package_init"}


def main_slot_filenames(slots: list[dict]) -> tuple[str, ...]:
    out: list[str] = []
    for sl in slots:
        if not isinstance(sl, dict):
            continue
        role = (sl.get("role") or "").strip().lower()
        if role in MAIN_SLOT_ROLES:
            fn = (sl.get("filename") or "").strip()
            if fn:
                out.append(fn)
    return tuple(out)


def parse_fix_elsewhere_marker(suggested: str) -> tuple[str | None, str | None]:
    """
    AI가 * DW-FIX-ELSEWHERE: 수정 대상=... | 이유=... 주석을 넣은 경우 파싱.
    """
    text = suggested or ""
    m = _FIX_ELSEWHERE_RE.search(text)
    if not m:
        return None, None
    line = (m.group(1) or "").strip()
    target = None
    reason = None
    for part in re.split(r"\|", line):
        p = part.strip()
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k in ("수정 대상", "target", "file", "파일"):
                target = v or None
            elif k in ("이유", "reason", "why"):
                reason = v or None
        elif target is None:
            target = p
    return target, reason


def _source_without_elsewhere_comments(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        if _FIX_ELSEWHERE_RE.match(ln):
            continue
        if re.match(r"(?i)^\s*\*\s*DW-FIX-ELSEWHERE", ln):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def suggestion_defers_fix_elsewhere(
    suggested: str,
    original: str,
    *,
    similarity_threshold: float = 0.92,
) -> tuple[bool, str | None, str | None]:
    """
    INCLUDE 등에서 오류만 보고 잘못 패치하는 경우: AI가 주석으로 다른 파일 수정을 권고하고
    본문은 거의 그대로 둔 응답인지 판별.
    """
    target, reason = parse_fix_elsewhere_marker(suggested)
    if not target and not _FIX_ELSEWHERE_RE.search(suggested or ""):
        return False, None, None
    o = _source_without_elsewhere_comments(original)
    s = _source_without_elsewhere_comments(suggested)
    if not o and not s:
        return True, target, reason
    if o == s:
        return True, target, reason
    o_lines = _line_count(o)
    s_lines = _line_count(s)
    if o_lines == 0:
        return True, target, reason
    ratio = s_lines / o_lines if o_lines else 1.0
    if ratio >= similarity_threshold and o in s or s in o:
        return True, target, reason
    # 주석만 있고 본문 변경이 극소(5줄 이하 diff)
    if abs(s_lines - o_lines) <= 5 and ratio >= 0.85:
        return True, target, reason
    return False, target, reason


def cross_slot_fix_hints(
    se38_error: str,
    slots: list[dict],
    *,
    active_index: int,
) -> tuple[str, ...]:
    """
    SE38 메시지에 다른 슬롯(INCLUDE 등) 이름이 보이면 안내용 파일명 반환.
    """
    err = (se38_error or "").lower()
    if not err.strip():
        return ()
    out: list[str] = []
    for i, sl in enumerate(slots):
        if i == active_index or not isinstance(sl, dict):
            continue
        fn = (sl.get("filename") or "").strip()
        if not fn:
            continue
        base = fn.lower()
        stem = base.rsplit(".", 1)[0] if "." in base else base
        if base in err or stem in err:
            out.append(fn)
    return tuple(out)


def line_number_gutter(text: str, *, max_lines: int = 8000) -> str:
    """표시용 행 번호 열(1..N). 저장 소스에는 넣지 않음."""
    lines = (text or "").splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        extra = "…"
    else:
        extra = None
    nums = [str(i) for i in range(1, len(lines) + 1)]
    if not nums:
        nums = ["1"]
    if extra:
        nums.append("…")
    width = max(4, len(nums[-1]))
    return "\n".join(n.rjust(width) for n in nums)
