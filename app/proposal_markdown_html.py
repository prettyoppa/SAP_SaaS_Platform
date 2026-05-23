"""개발 제안서·FS 등 Markdown → HTML (화면 proposal-body와 동일 파이프라인)."""

from __future__ import annotations

import re

from .agent_display import wrap_unbracketed_agent_names


def _is_md_table_row(s: str) -> bool:
    t = s.strip()
    if "|" not in t or t.count("|") < 2:
        return False
    return t.startswith("|")


def _is_md_table_separator(s: str) -> bool:
    t = s.strip()
    if "|" not in t or "-" not in t:
        return False
    for ch in t:
        if ch not in "|-:+ \t|":
            return False
    return True


def _md_table_cells(line: str) -> list[str]:
    parts = [p.strip() for p in line.strip().split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _md_cell_inline_html(raw: str) -> str:
    from markupsafe import escape

    t = escape(str(raw))
    if "**" not in t:
        return t
    parts = t.split("**")
    out: list[str] = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(p)
        else:
            out.append(f"<strong>{p}</strong>")
    return "".join(out)


def _gfm_table_block_to_html(rows: list[str]) -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        cells = _md_table_cells(rows[0])
        if not any(c.strip() for c in cells):
            return ""
        tds = "".join(f"<td>{_md_cell_inline_html(c)}</td>" for c in cells)
        return (
            '<div class="proposal-table-wrap my-3">'
            '<table class="table table-bordered table-sm proposal-md-table align-middle">'
            f"<tbody><tr>{tds}</tr></tbody></table></div>"
        )
    if len(rows) >= 2 and _is_md_table_separator(rows[1]):
        head = _md_table_cells(rows[0])
        data_lines = rows[2:]
    else:
        head = _md_table_cells(rows[0])
        data_lines = rows[1:]

    ncols = max(
        len(head),
        max((len(_md_table_cells(x)) for x in data_lines), default=0),
    )
    ths = "".join(
        f'<th scope="col">{_md_cell_inline_html(head[i] if i < len(head) else "")}</th>'
        for i in range(ncols)
    )
    trs: list[str] = []
    for line in data_lines:
        b = _md_table_cells(line)
        tds = "".join(
            f"<td>{_md_cell_inline_html(b[i] if i < len(b) else '')}</td>" for i in range(ncols)
        )
        trs.append(f"<tr>{tds}</tr>")
    return (
        '<div class="proposal-table-wrap my-3">'
        '<table class="table table-bordered table-sm proposal-md-table align-middle">'
        f'<thead class="table-light"><tr>{ths}</tr></thead>'
        f"<tbody>{''.join(trs)}</tbody></table></div>"
    )


def _extract_md_tables_to_placeholders(md: str) -> tuple[str, list[str]]:
    """GFM 스타일 | 표| 를 잡아 HTML로 변환한 뒤 자리 표시자로 치환(이후 본문 처리)."""
    lines = md.split("\n")
    out_lines: list[str] = []
    tables: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_md_table_row(lines[i]):
            out_lines.append(lines[i])
            i += 1
            continue
        j, block = i, []
        while j < n:
            s = lines[j]
            if s.strip() == "":
                if j + 1 < n and _is_md_table_row(lines[j + 1]):
                    j += 1
                    continue
                break
            if _is_md_table_row(s):
                block.append(s)
                j += 1
            else:
                break
        if block:
            tables.append(_gfm_table_block_to_html(block))
            out_lines.append(f"__MDTABLE{len(tables) - 1}__")
            out_lines.append("")
        i = j
    return "\n".join(out_lines), tables


def markdown_to_html(md: str) -> str:
    """허브 proposal-body와 동일한 HTML 조각을 반환."""
    md = wrap_unbracketed_agent_names(md or "")
    md, table_parts = _extract_md_tables_to_placeholders(md)
    html = md
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^---+$", r"<hr>", html, flags=re.MULTILINE)

    lines = html.split("\n")
    result, in_list, list_type = [], False, None
    for line in lines:
        s = line.strip()
        m_tbl = re.match(r"^__MDTABLE(\d+)__$", s)
        if m_tbl:
            if in_list:
                result.append(f"</{list_type}>")
                in_list, list_type = False, None
            idx = int(m_tbl.group(1))
            if 0 <= idx < len(table_parts):
                result.append(table_parts[idx])
            continue
        if s.startswith("- "):
            if not in_list or list_type != "ul":
                if in_list:
                    result.append(f"</{list_type}>")
                result.append("<ul>")
                in_list, list_type = True, "ul"
            result.append(f"<li>{s[2:]}</li>")
        elif re.match(r"^\d+\.", s):
            if not in_list or list_type != "ol":
                if in_list:
                    result.append(f"</{list_type}>")
                result.append("<ol>")
                in_list, list_type = True, "ol"
            item_text = re.sub(r"^\d+\.\s*", "", s)
            result.append(f"<li>{item_text}</li>")
        else:
            if in_list:
                result.append(f"</{list_type}>")
                in_list, list_type = False, None
            result.append(f"<p>{line}</p>" if s and not s.startswith("<") else line)

    if in_list:
        result.append(f"</{list_type}>")
    return wrap_unbracketed_agent_names("\n".join(result))
