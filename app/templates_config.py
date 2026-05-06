"""
공유 Jinja2Templates 인스턴스 – 모든 라우터가 이 모듈에서 import합니다.
main.py 에서 직접 생성하지 않고 여기서 한 번만 생성하여 필터가 일관되게 적용됩니다.
"""
import json as _json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .agent_display import agent_label_ko
from .rfp_phase_gates import rfp_phase_gates

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.filters["from_json"] = _json.loads


def _tojson_filter(v) -> Markup:
    s = _json.dumps(v, ensure_ascii=False)
    s = s.replace("<", "\\u003c").replace(">", "\\u003e")
    return Markup(s)


templates.env.filters["tojson"] = _tojson_filter


def _interview_bold_filter(s) -> Markup:
    """질문/답에 남은 **text** 를 HTML 볼드로 변환(이스케이프 유지)."""
    if s is None:
        return Markup("")
    t = escape(str(s))
    if "**" not in t:
        return Markup(t)
    parts = t.split("**")
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(p)
        else:
            out.append(f'<strong class="interview-em">{p}</strong>')
    return Markup("".join(out))


templates.env.filters["interview_bold"] = _interview_bold_filter
templates.env.filters["agent_label"] = agent_label_ko
templates.env.filters["phase_gates"] = rfp_phase_gates


def _utc_iso_for_attr(dt) -> str:
    """DB에 저장된 naive UTC 시각을 ISO8601(Z) 문자열로(클라이언트 변환용)."""
    if dt is None:
        return ""
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _local_dt_span_filter(dt, fmt: str = "datetime") -> Markup:
    """
    UTC 기준 시각을 data-utc로 내보내고, /static/js/main.js 가 프로필·브라우저 타임존으로 치환.
    fmt: datetime | date | date_dots
    """
    if dt is None:
        return Markup("—")
    iso = _utc_iso_for_attr(dt)
    if not iso:
        return Markup("—")
    f = (fmt or "datetime").strip() or "datetime"
    return Markup(
        f'<span class="local-dt" data-utc="{escape(iso)}" data-fmt="{escape(f)}">…</span>'
    )


templates.env.filters["utc_iso"] = _utc_iso_for_attr
templates.env.filters["local_dt_span"] = _local_dt_span_filter


def _request_no_filter(v, prefix: str = "REQ") -> str:
    """요청 식별번호를 화면 표기용으로 통일 (예: RFP-000123)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    p = (prefix or "REQ").strip().upper()
    return f"{p}-{n:06d}"


templates.env.filters["request_no"] = _request_no_filter
