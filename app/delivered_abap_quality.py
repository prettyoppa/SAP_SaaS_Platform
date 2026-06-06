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

# SE38 활성화·구문check에서 자주 터지는 패턴 (정적 힌트 — codegen·2차 검수에 사용)
SE38_SEMANTIC_REVIEW_RULES_KO = """
### SE38 활성화 전 필수 점검 (표면 구문·API 오용)
- Selection Screen `PARAMETERS`/`SELECT-OPTIONS`에 **TYPE string** 사용 금지 → `TYPE c LENGTH n` 또는 텍스트 요소.
- **`TYPE boolean`** 금지 → `TYPE xfeld` / `TYPE abap_bool` / `TYPE c LENGTH 1` 등 표준 타입.
- 동일 **TEXT-xxx** 를 COMMENT와 PUSHBUTTON(또는 다른 UI)에 **중복** 사용 금지.
- `cl_abap_char_utilities=>dir_sep` **없음** → `CL_GUI_FRONTEND_SERVICES` 또는 OS별 리터럴/`/` 조합.
- `GUI_DOWNLOAD`: **`xstring` 파라미터 없음** → `DATA_TAB` + `CHANGING`/`TABLES` 방식.
- `CL_GUI_FRONTEND_SERVICES` 등 **classic FM**에 `TRY/CATCH cx_frontend_services` **불필요·오류** — 레거시 FM은 sy-subrc.
- `SET_SCREEN_STATUS`/`PF-STATUS`: 소스에 **정의되지 않은** `STANDARD_FULLSCREEN` 등 임의 PF-STATUS 금지.
- ALV: `if_salv_c_cell_type=>checkbox` **클릭 불가** → `checkbox_hotspot`; checkbox 이벤트 핸들러 필요 시 구현.
- `CALL METHOD`/`CALL FUNCTION` **파라미터 이름·종류**(IMPORTING/EXPORTING/CHANGING) 표준 API와 일치.
"""


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


def _lint_text_element_duplicates(
    lines: list[str],
    *,
    slot_index: int,
    filename: str,
) -> list[AbapLintIssue]:
    """COMMENT·PUSHBUTTON 등에서 동일 TEXT-xxx 중복."""
    comment_ids: set[str] = set()
    push_ids: set[str] = set()
    text_re = re.compile(r"(?i)\bTEXT-(\d+)\b")
    for line in lines:
        low = line.lower()
        ids = text_re.findall(line)
        if not ids:
            continue
        if "comment" in low or "selection-screen comment" in low:
            comment_ids.update(ids)
        if "pushbutton" in low or "user-command" in low:
            push_ids.update(ids)
    issues: list[AbapLintIssue] = []
    for tid in sorted(comment_ids & push_ids):
        issues.append(
            AbapLintIssue(
                severity="error",
                slot_index=slot_index,
                filename=filename,
                line_no=None,
                code="text_element_duplicate",
                message_ko=(
                    f"TEXT-{tid} 가 COMMENT와 PUSHBUTTON(또는 유사 UI)에 중복 — "
                    "SE38 Selection Screen 식별자 충돌."
                ),
            )
        )
    return issues


def lint_se38_semantic_patterns(
    source: str,
    *,
    slot_index: int = 0,
    filename: str = "",
) -> list[AbapLintIssue]:
    """SE38 활성화·구문check에서 흔한 API/타입 오류 (정적 패턴)."""
    issues: list[AbapLintIssue] = []
    if not (source or "").strip():
        return issues
    lines = source.splitlines()
    issues.extend(
        _lint_text_element_duplicates(lines, slot_index=slot_index, filename=filename)
    )
    for i, line in enumerate(lines, 1):
        if re.search(r"(?i)PARAMETERS\s+\w+.*TYPE\s+string\b", line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="param_type_string",
                    message_ko=(
                        f"{i}행: Selection Screen PARAMETERS에 TYPE string 불가 — "
                        "TYPE c LENGTH n 또는 텍스트 요소."
                    ),
                )
            )
        if re.search(r"(?i)\bTYPE\s+boolean\b", line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="type_boolean",
                    message_ko=f"{i}행: TYPE boolean 은 표준 ABAP 타입 아님 — xfeld/abap_bool 등 사용.",
                )
            )
        if re.search(r"(?i)cl_abap_char_utilities=>\s*dir_sep\b", line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="dir_sep_invalid",
                    message_ko=(
                        f"{i}행: cl_abap_char_utilities=>dir_sep 속성 없음 — "
                        "경로 구분은 CL_GUI_FRONTEND_SERVICES 등 표준 API 사용."
                    ),
                )
            )
        if re.search(r"(?i)\bgui_download\b", line) and re.search(r"(?i)\bxstring\s*=", line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="gui_download_xstring",
                    message_ko=(
                        f"{i}행: GUI_DOWNLOAD에 xstring 파라미터 없음 — "
                        "DATA_TAB + CHANGING/TABLES 방식."
                    ),
                )
            )
        if re.search(r"(?i)\bcx_frontend_service", line):
            issues.append(
                AbapLintIssue(
                    severity="warning",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="cx_frontend_services",
                    message_ko=(
                        f"{i}행: cx_frontend_services 계열 — "
                        "CL_GUI_FRONTEND_SERVICES 등 classic FM은 sy-subrc 확인."
                    ),
                )
            )
        if re.search(r"(?i)if_salv_c_cell_type=>\s*checkbox\b", line):
            issues.append(
                AbapLintIssue(
                    severity="error",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="salv_checkbox_type",
                    message_ko=(
                        f"{i}행: if_salv_c_cell_type=>checkbox 클릭 불가 — "
                        "checkbox_hotspot 사용."
                    ),
                )
            )
        if re.search(r"(?i)pfstatus\s*=\s*['\"]standard_fullscreen['\"]", line):
            issues.append(
                AbapLintIssue(
                    severity="warning",
                    slot_index=slot_index,
                    filename=filename,
                    line_no=i,
                    code="pf_status_undefined",
                    message_ko=(
                        f"{i}행: PF-STATUS 'STANDARD_FULLSCREEN' — "
                        "MODULE STATUS에서 정의되지 않았을 수 있음."
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
    issues.extend(
        lint_se38_semantic_patterns(source, slot_index=slot_index, filename=filename)
    )
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


def append_lint_coder_notes(data: dict[str, Any], issues: list[AbapLintIssue]) -> dict[str, Any]:
    """잔여 린트를 coder_notes에 기록 — ZIP·로컬 IDE(Cursor)에서 우선 수정."""
    if not issues or not isinstance(data, dict):
        return data
    out = dict(data)
    block = format_lint_for_reviewer(issues, max_items=14)
    note = (
        "### 정적 품질 검사 잔여 (로컬 IDE에서 우선 수정)\n"
        "SE38 활성화 전 아래 항목을 Cursor 등에서 먼저 해소하세요.\n\n"
        + block
    )
    prev = (str(out.get("coder_notes") or "")).strip()
    out["coder_notes"] = (prev + "\n\n" + note).strip() if prev else note
    return out


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


def needs_third_lint_pass(issues: list[AbapLintIssue]) -> bool:
    """2차 검수·보정 후에도 린트가 남으면 3차(최종) 자동 수정."""
    return len(issues) > 0


def lint_fix_pass_instructions(pass_no: int) -> str:
    """코드생성 파이프라인 2·3차 검수 지시문."""
    if pass_no >= 3:
        return """
### 3차 검수 (최종 자동 수정)
- 이번이 **마지막** 자동 수정입니다. **순수 JSON 하나**만 출력.
- **error severity 항목은 0건**이 되도록 반드시 해소하세요.
- warning도 가능한 한 해소. FS·기능·로직 **대규모 변경 금지**.
- **블록 짝**(SELECT/ENDSELECT, LOOP/ENDLOOP, IF/ENDIF, FORM/ENDFORM 등)을 먼저 맞춘 뒤 SE38 표면 구문·API 오용만 고칩니다.
- Windows 경로: JSON에서 `C:\\\\temp`. REPORT 1열, 공백 2칸, 탭 제거.
"""
    return """
### 2차 검수 지시
- 위 **모든** 정적 검사 항목을 해소한 **순수 JSON 하나**만 출력.
- **블록 짝**(SELECT/ENDSELECT, LOOP/ENDLOOP, IF/ENDIF, FORM/ENDFORM 등)을 먼저 맞춘 뒤 세부 로직을 검토한다.
- Windows 경로: JSON에서 `C:\\\\temp`. REPORT 1열, 공백 2칸, 탭 제거.
- FS·기능 변경 없이 **포맷·블록 구조·표면 구문·SE38 활성화 오류 패턴**만 고친다 (엉뚱한 로직 수정 금지).
"""
