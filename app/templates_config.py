"""
공유 Jinja2Templates 인스턴스 – 모든 라우터가 이 모듈에서 import합니다.
main.py 에서 직접 생성하지 않고 여기서 한 번만 생성하여 필터가 일관되게 적용됩니다.
"""
import json as _json
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

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
