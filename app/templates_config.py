"""
공유 Jinja2Templates 인스턴스 – 모든 라우터가 이 모듈에서 import합니다.
main.py 에서 직접 생성하지 않고 여기서 한 번만 생성하여 필터가 일관되게 적용됩니다.
"""
import json as _json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi.encoders import jsonable_encoder
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .agent_display import agent_label_ko
from .home_hero_defaults import DEFAULT_HOME_HERO_HTML
from .youtube_embed import youtube_embed_info, youtube_video_id
from .rfp_phase_gates import integration_phase_gates, rfp_phase_gates, abap_analysis_phase_gates

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.filters["from_json"] = _json.loads


def _tojson_filter(v) -> Markup:
    try:
        s = _json.dumps(v, ensure_ascii=False)
    except TypeError:
        s = _json.dumps(jsonable_encoder(v), ensure_ascii=False)
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
templates.env.filters["integration_phase_gates"] = integration_phase_gates
templates.env.filters["abap_analysis_phase_gates"] = abap_analysis_phase_gates


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
    """요청 식별번호를 화면 표기용으로 통일 (예: RFP-123, 앞자리 0 없음)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    p = (prefix or "REQ").strip().upper()
    return f"{p}-{n}"


templates.env.filters["request_no"] = _request_no_filter


def _review_author_label_filter(review) -> str:
    from .review_ratings_util import review_author_label

    return review_author_label(review)


templates.env.filters["review_author_label"] = _review_author_label_filter


def _md_html_filter(s) -> Markup:
    """제목·본문 등 저장된 마크다운을 HTML로 (interview_router 구현 재사용)."""
    if s is None:
        return Markup("")
    raw = str(s).strip()
    if not raw:
        return Markup("")
    from .routers.interview_router import _markdown_to_html

    return Markup(_markdown_to_html(raw))


templates.env.filters["md_html"] = _md_html_filter


def _req_analysis_html_filter(value) -> Markup:
    from .analysis_display import format_requirement_analysis_field

    return format_requirement_analysis_field(value)


templates.env.filters["req_analysis_html"] = _req_analysis_html_filter


def _req_analysis_li_filter(value) -> Markup:
    from .analysis_display import format_requirement_analysis_list_item

    return format_requirement_analysis_list_item(value)


templates.env.filters["req_analysis_li"] = _req_analysis_li_filter


def _requirement_preview_filter(row, limit: int = 180) -> str:
    """목록 카드용 요구사항 한 줄 미리보기(HTML → plain)."""
    from .requirement_rich_text import html_to_plain_text, is_html_format

    raw = (getattr(row, "requirement_text", None) or "").strip()
    if not raw:
        return ""
    fmt = (getattr(row, "requirement_text_format", None) or "plain").strip().lower()
    plain = html_to_plain_text(raw) if is_html_format(fmt) else raw
    plain = " ".join(plain.split())
    lim = int(limit) if limit else 180
    if len(plain) > lim:
        return plain[:lim] + "…"
    return plain


templates.env.filters["requirement_preview"] = _requirement_preview_filter


def _interview_answers_text_to_qa_pairs(text) -> list[dict[str, str]]:
    """인터뷰 라운드 answers_text(Q1:/A1: 블록) → 메신저용 Q/A 쌍."""
    import re

    s = (text or "").strip()
    if not s:
        return []
    parts = re.split(r"\n\n(?=Q\d+:)", s)
    out: list[dict[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^Q(\d+):\s*\n?(.*)\n\nA\1:\s*\n?(.*)$", part, re.DOTALL)
        if m:
            out.append({"q": m.group(2).strip(), "a": m.group(3).strip()})
        else:
            out.append({"q": "", "a": part})
    if not out and s:
        return [{"q": "", "a": s}]
    return out


def _interview_qa_pairs_filter(text) -> list[dict[str, str]]:
    return _interview_answers_text_to_qa_pairs(text)


templates.env.filters["interview_qa_pairs"] = _interview_qa_pairs_filter
templates.env.filters["urlquote"] = lambda s: quote_plus(str(s or ""))
templates.env.filters["youtube_video_id"] = youtube_video_id
templates.env.filters["youtube_embed"] = youtube_embed_info

templates.env.globals["default_home_hero_html"] = DEFAULT_HOME_HERO_HTML


def layout_template_from_embed_query(request) -> str:
    """?embed=1|true|yes 이면 iframe 등 임베드용 레이아웃(네비·푸터 없음)."""
    raw = ""
    try:
        raw = (request.query_params.get("embed") or "").strip().lower()
    except Exception:
        raw = ""
    return "base_embed.html" if raw in ("1", "true", "yes") else "base.html"
