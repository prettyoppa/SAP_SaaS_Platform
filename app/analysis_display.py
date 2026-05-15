"""요구사항 연계 분석(interpretation, mapping 등) 화면 표시용 HTML 포맷."""

from __future__ import annotations

import ast
import json
from typing import Any

from markupsafe import Markup, escape


def _coerce_mapping_value(value: Any) -> Any:
    """LLM이 dict를 문자열(Python/JSON)로 넣은 경우 파싱."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return ""
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (dict, list)):
                return parsed
        except (SyntaxError, ValueError):
            pass
    return value


def _issue_block_html(key: str, val: Any) -> str:
    title = escape(str(key).replace("_", " "))
    if isinstance(val, dict):
        desc = (
            val.get("description")
            or val.get("summary")
            or val.get("text")
            or ""
        )
        refs = val.get("code_references") or val.get("references") or val.get("refs")
        parts = [
            '<div class="analysis-mapping-block mb-3">',
            f'<div class="analysis-mapping-key fw-semibold small text-uppercase text-muted mb-1">{title}</div>',
        ]
        if desc:
            parts.append(
                f'<p class="analysis-mapping-desc mb-2">{escape(str(desc).strip())}</p>'
            )
        if refs:
            items = refs if isinstance(refs, list) else [refs]
            parts.append('<ul class="analysis-list mb-0">')
            for r in items:
                t = str(r).strip()
                if t:
                    parts.append(f"<li><code>{escape(t)}</code></li>")
            parts.append("</ul>")
        if not desc and not refs:
            for k, v in val.items():
                if v is not None and str(v).strip():
                    parts.append(
                        f'<p class="mb-1"><span class="text-muted">{escape(str(k))}:</span> '
                        f"{escape(str(v).strip())}</p>"
                    )
        parts.append("</div>")
        return "".join(parts)
    if isinstance(val, list):
        inner = "".join(
            f"<li>{escape(str(x).strip())}</li>" for x in val if str(x).strip()
        )
        return (
            f'<div class="analysis-mapping-block mb-3">'
            f'<div class="analysis-mapping-key fw-semibold small mb-1">{title}</div>'
            f'<ul class="analysis-list mb-0">{inner}</ul></div>'
        )
    return (
        f'<div class="analysis-mapping-block mb-3">'
        f'<div class="analysis-mapping-key fw-semibold small mb-1">{title}</div>'
        f'<p class="mb-0">{escape(str(val).strip())}</p></div>'
    )


def _dict_to_html(d: dict) -> str:
    """이슈 키 → {description, code_references} 형태 우선."""
    if not d:
        return ""
    issue_like = all(isinstance(v, (dict, list, str)) for v in d.values())
    if issue_like and any(
        isinstance(v, dict) and ("description" in v or "code_references" in v)
        for v in d.values()
    ):
        return "".join(_issue_block_html(k, v) for k, v in d.items())
    blocks: list[str] = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            blocks.append(_issue_block_html(str(k), v))
        else:
            blocks.append(
                f'<p class="mb-2"><span class="fw-semibold">{escape(str(k))}:</span> '
                f"{escape(str(v).strip())}</p>"
            )
    return "".join(blocks)


def _list_to_html(items: list) -> str:
    inner = "".join(
        f"<li>{escape(str(x).strip())}</li>" for x in items if str(x).strip()
    )
    if not inner:
        return ""
    return f'<ul class="analysis-list mb-0">{inner}</ul>'


def _plain_text_html(s: str) -> str:
    t = s.strip()
    if not t:
        return ""
    if "\n" in t or len(t) > 120:
        return f'<div class="analysis-pre-wrap">{escape(t)}</div>'
    return f'<p class="mb-0">{escape(t)}</p>'


def format_requirement_analysis_list_item(value: Any) -> Markup:
    """가설·검증 제안 등 목록 한 줄 — **굵게**, `코드` 인라인 마크다운."""
    import re

    from .routers.interview_router import _markdown_to_html

    s = str(value or "").strip()
    if not s:
        return Markup("")
    html = _markdown_to_html(s).strip()
    m = re.fullmatch(r"<p>(.+)</p>", html, flags=re.DOTALL)
    if m:
        html = m.group(1).strip()
    return Markup(html)


def format_requirement_analysis_field(value: Any) -> Markup:
    """interpretation / mapping 등 — dict·목록·여러 줄 문자열을 읽기 쉬운 HTML로."""
    coerced = _coerce_mapping_value(value)
    if coerced is None or coerced == "":
        return Markup("")
    if isinstance(coerced, dict):
        return Markup(_dict_to_html(coerced))
    if isinstance(coerced, list):
        return Markup(_list_to_html(coerced))
    if isinstance(coerced, str):
        return Markup(_plain_text_html(coerced))
    return Markup(_plain_text_html(str(coerced)))
