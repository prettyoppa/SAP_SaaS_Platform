"""SE38 납품 작업실 — 컨설턴트가 붙인 오류·구문에 AI가 집중하도록 힌트 생성."""

from __future__ import annotations

import re


def extract_consultant_snippet(se38_error: str) -> str:
    """SE38 입력란에 붙인 ABAP 구문·오류 메시지 줄만 추출."""
    lines: list[str] = []
    for ln in (se38_error or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.search(
            r"(?i)^(call\s+method|call\s+function|method\s+|form\s+|function\s+|"
            r"data:|types:|constants:|\*\s*syntax|----)",
            s,
        ):
            lines.append(ln.rstrip())
        elif re.search(
            r"(?i)(exporting|importing|changing|returning|tables|exceptions|=>|cl_)",
            s,
        ):
            lines.append(ln.rstrip())
        elif re.search(r"(?i)(formal parameter|syntax error|activation error)", s):
            lines.append(ln.rstrip())
        elif re.search(r"(?i)^[a-z][a-z0-9_]*\s*$", s) and len(s) < 48:
            # 프로그램/INCLUDE 이름 단독 줄 (ZSDSRCTAB_DL2_FORMS)
            lines.append(ln.rstrip())
    return "\n".join(lines[:120]).strip()


def find_snippet_anchor_line(snippet: str, source: str) -> int | None:
    """붙인 구문이 소스에서 시작하는 대략적 행 번호(1-based)."""
    if not (snippet or "").strip() or not (source or "").strip():
        return None
    src_lines = source.splitlines()
    for cand in snippet.splitlines():
        c = cand.strip()
        if len(c) < 10:
            continue
        needle = re.sub(r"\s+", "", c.lower())[:48]
        if len(needle) < 10:
            continue
        for i, sl in enumerate(src_lines):
            hay = re.sub(r"\s+", "", sl.lower())
            if needle in hay or hay in needle:
                return i + 1
    return None


def build_se38_focus_section(se38_error: str, source: str) -> str:
    """프롬프트에 붙일 '이번 오류 집중' 블록."""
    err = (se38_error or "").strip()
    parts: list[str] = [
        "## 이번 SE38 오류에 집중 (필수)",
        "- 컨설턴트가 [SE38 오류·징후]에 적은 **메시지·붙인 구문**만 1순위로 수정하세요.",
        "- 다른 행의 잠재 오타·경로 문자열·스타일은 **이번 응답에서 수정하지 마세요** (활성화에 필수일 때만 예외).",
    ]
    m = re.search(r'formal parameter\s+"([^"]+)"\s+does not exist', err, re.I)
    if m:
        param = m.group(1)
        parts.append(
            f'- SE38: 형식 파라미터 "{param}" 없음 → 해당 CALL/FM/메서드의 **실제 시그니처**에 맞게 '
            "IMPORTING/EXPORTING/CHANGING/RETURNING·이름만 최소 수정."
        )
    snippet = extract_consultant_snippet(err)
    if snippet:
        parts.append("- 컨설턴트가 강조한 구문(최우선 수정 대상):\n```\n" + snippet[:4000] + "\n```")
        anchor = find_snippet_anchor_line(snippet, source)
        if anchor:
            parts.append(
                f"- 현재 슬롯 소스 **추정 위치: 약 {anchor}행** 부근. 이 구간의 CALL/선언을 우선 고치세요."
            )
    err_lower = err.lower()
    if "file_save_dialog" in err_lower and "rc" in err_lower:
        parts.append(
            "- 참고: `CL_GUI_FRONTEND_SERVICES=>FILE_SAVE_DIALOG` 에서 `rc` 는 일반적으로 "
            "**EXPORTING** 입니다. `CHANGING rc =` 는 본 오류의 전형적 원인입니다. **해당 CALL만** 고치세요."
        )
    return "\n".join(parts) + "\n"
