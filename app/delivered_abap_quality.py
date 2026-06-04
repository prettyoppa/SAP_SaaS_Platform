"""납품 ABAP 슬롯 — 정적 품질 검사·자동 보정(SE38 Pretty Printer·경로 문자열)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning"]

# Pretty Printer·구문check 전에 맞춰야 할 블록 쌍 (개수 불일치 = error)
_BLOCK_PAIRS: tuple[tuple[str, str], ...] = (
    ("SELECT", "ENDSELECT"),
    ("LOOP", "ENDLOOP"),
    ("IF", "ENDIF"),
    ("FORM", "ENDFORM"),
    ("CASE", "ENDCASE"),
    ("DO", "ENDDO"),
    ("WHILE", "ENDWHILE"),
    ("TRY", "ENDTRY"),
    ("METHOD", "ENDMETHOD"),
    ("MODULE", "ENDMODULE"),
)

_PATH_TAB_CORRUPT = re.compile(
    r"(['\"])([A-Za-z]:\\)(\t+)(emp)(['\"])",
)
_PATH_SPACE_CORRUPT = re.compile(
    r"(['\"])([A-Za-z]:\\)\s+(emp)(['\"])",
)
_REPORT_LINE = re.compile(r"^\s*(REPORT|PROGRAM)\s+\S", re.I)
_ABAP_KEYWORD_LINE = re.compile(
    r"^(\s*)(DATA|CONSTANTS|TYPES|SELECT|IF|ELSE|ENDIF|CALL|METHOD|FORM|ENDFORM|"
    r"LOOP|ENDLOOP|CASE|WHEN|ENDCASE|INCLUDE|REPORT|PROGRAM)\b",
    re.I,
)
_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")


@dataclass(frozen=True)
class AbapLintIssue:
    severity: Severity
    slot_index: int
    filename: str
    line_no: int | None
    code: str
    message_ko: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "slot_index": self.slot_index,
            "filename": self.filename,
            "line_no": self.line_no,
            "code": self.code,
            "message_ko": self.message_ko,
        }


def fix_corrupted_windows_paths(source: str) -> tuple[str, list[str]]:
    """JSON/LLM 이스케이프로 `C:\\temp` 가 `C:\\<TAB>emp` 로 깨진 경우 복구."""
    fixes: list[str] = []
    s = source or ""

    def _tab_repl(m: re.Match[str]) -> str:
        fixes.append(f"Windows path tab corruption near {m.group(2)}emp")
        return f"{m.group(1)}{m.group(2)}t{m.group(4)}{m.group(5)}"

    def _sp_repl(m: re.Match[str]) -> str:
        fixes.append(f"Windows path spacing corruption near {m.group(2)}emp")
        return f"{m.group(1)}{m.group(2)}temp{m.group(4)}"

    s2 = _PATH_TAB_CORRUPT.sub(_tab_repl, s)
    s2 = _PATH_SPACE_CORRUPT.sub(_sp_repl, s2)
    return s2, fixes


def normalize_abap_source_layout(source: str) -> tuple[str, list[str]]:
    """Pretty Printer 전 단계: 탭→공백, REPORT/PROGRAM 선행 공백 제거, 줄 끝 공백."""
    fixes: list[str] = []
    if not (source or "").strip():
        return source or "", fixes
    out_lines: list[str] = []
    for i, raw in enumerate(source.splitlines(), 1):
        line = raw.rstrip()
        if "\t" in line:
            line = line.replace("\t", "  ")
            fixes.append(f"line {i}: tab→spaces")
        if _REPORT_LINE.match(line) and line[:1].isspace():
            line = line.lstrip()
            fixes.append(f"line {i}: REPORT/PROGRAM dedented to column 0")
        out_lines.append(line)
    return "\n".join(out_lines), fixes


def harden_slot_source(source: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    s = source or ""
    s, f1 = fix_corrupted_windows_paths(s)
    notes.extend(f1)
    s, f2 = normalize_abap_source_layout(s)
    notes.extend(f2)
    return s, notes


def _source_for_structure_scan(source: str) -> str:
    """주석·문자열 리터럴을 제거한 뒤 블록 키워드만 센다."""
    lines_out: list[str] = []
    for raw in (source or "").splitlines():
        line = raw.split('"')[0] if '"' in raw else raw
        if line.strip().startswith("*"):
            continue
        line = _STRING_LITERAL.sub("''", line)
        lines_out.append(line)
    return "\n".join(lines_out)


def _count_keyword(text: str, keyword: str) -> int:
    return len(re.findall(rf"(?i)\b{re.escape(keyword)}\b", text))


def lint_block_balance(
    source: str,
    *,
    slot_index: int = 0,
    filename: str = "",
) -> list[AbapLintIssue]:
    """SELECT~ENDSELECT 등 블록 짝 불일치 — Pretty Printer 실패의 직접 원인."""
    issues: list[AbapLintIssue] = []
    scanned = _source_for_structure_scan(source)
    if not scanned.strip():
        return issues
    for open_kw, close_kw in _BLOCK_PAIRS:
        o = _count_keyword(scanned, open_kw)
        c = _count_keyword(scanned, close_kw)
        if o == c:
            continue
        if o == 0 and c == 0:
            continue
        issues.append(
            AbapLintIssue(
                severity="error",
                slot_index=slot_index,
                filename=filename,
                line_no=None,
                code=f"block_{open_kw.lower()}",
                message_ko=(
                    f"{open_kw} {o}개 / {close_kw} {c}개 — 블록 짝 불일치. "
                    "Pretty Printer·구문check 전에 반드시 맞출 것 (엉뚱한 syntax error 유발)."
                ),
            )
        )
    return issues


def lint_slot_source(
    source: str,
    *,
    slot_index: int = 0,
    filename: str = "",
) -> list[AbapLintIssue]:
    issues: list[AbapLintIssue] = []
    if not (source or "").strip():
        return issues
    lines = source.splitlines()
    issues.extend(lint_block_balance(source, slot_index=slot_index, filename=filename))
    for i, line in enumerate(lines, 1):
        if _PATH_TAB_CORRUPT.search(line) or _PATH_SPACE_CORRUPT.search(line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="path_tab_corrupt",
                    message_ko=(
                        f"{i}행: Windows 경로 문자열이 깨졌습니다 "
                        "(예: C:\\\\temp → \\\\t 이 탭으로 해석). C:\\\\temp 형태로 수정."
                    ),
                )
            )
        if _REPORT_LINE.match(line) and line[:1].isspace():
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="report_indent",
                    message_ko=f"{i}행: REPORT/PROGRAM 은 1열(앞 공백 없음)에서 시작해야 SE38 Pretty Printer 통과.",
                )
            )
        if "\t" in line:
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="tab_char",
                    message_ko=f"{i}행: 탭 문자 — 공백 2칸 들여쓰기만 사용 (Pretty Printer).",
                )
            )
        m = _ABAP_KEYWORD_LINE.match(line)
        if m and len(m.group(1)) % 2 != 0:
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="odd_indent",
                    message_ko=f"{i}행: 들여쓰기 2칸 단위 아님 — Pretty Printer 정렬 실패 가능.",
                )
            )
    return issues


def harden_delivered_package_dict(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """슬롯 source에 자동 보정 적용. 원본 dict 복사."""
    if not isinstance(data, dict):
        return data, []
    out = dict(data)
    slots = out.get("slots")
    if not isinstance(slots, list):
        return out, []
    all_notes: list[str] = []
    new_slots: list[Any] = []
    for i, sl in enumerate(slots):
        if not isinstance(sl, dict):
            new_slots.append(sl)
            continue
        sl2 = dict(sl)
        src = str(sl2.get("source") or "")
        hardened, notes = harden_slot_source(src)
        sl2["source"] = hardened
        fn = (sl2.get("filename") or f"slot_{i + 1}.abap").strip()
        for n in notes:
            all_notes.append(f"{fn}: {n}")
        new_slots.append(sl2)
    out["slots"] = new_slots
    if all_notes:
        prev = (str(out.get("coder_notes") or "")).strip()
        block = "자동 품질 보정: " + "; ".join(all_notes[:12])
        if len(all_notes) > 12:
            block += f" … 외 {len(all_notes) - 12}건"
        out["coder_notes"] = (prev + "\n" + block).strip() if prev else block
    return out, all_notes


def lint_delivered_package(data: dict[str, Any]) -> list[AbapLintIssue]:
    issues: list[AbapLintIssue] = []
    if not isinstance(data, dict):
        return issues
    slots = data.get("slots")
    if not isinstance(slots, list):
        return issues
    for i, sl in enumerate(slots):
        if not isinstance(sl, dict):
            continue
        fn = (sl.get("filename") or f"slot_{i + 1}.abap").strip()
        issues.extend(
            lint_slot_source(str(sl.get("source") or ""), slot_index=i, filename=fn)
        )
    return issues


def format_lint_for_reviewer(issues: list[AbapLintIssue], *, max_items: int = 24) -> str:
    if not issues:
        return "(정적 검사 이슈 없음)"
    lines: list[str] = []
    for iss in issues[:max_items]:
        loc = f"{iss.filename}"
        if iss.line_no:
            loc += f":{iss.line_no}"
        lines.append(f"- [{iss.severity}] {loc} — {iss.message_ko}")
    if len(issues) > max_items:
        lines.append(f"- … 외 {len(issues) - max_items}건")
    return "\n".join(lines)


def package_has_blocking_lint(issues: list[AbapLintIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


def package_needs_second_review(issues: list[AbapLintIssue]) -> bool:
    """자동 보정 후에도 린트 이슈가 하나라도 남으면 2차 검수 (포맷·블록 구조 우선)."""
    return len(issues) > 0
