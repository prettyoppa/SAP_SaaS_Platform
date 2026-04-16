"""
공유 Jinja2Templates 인스턴스 – 모든 라우터가 이 모듈에서 import합니다.
main.py 에서 직접 생성하지 않고 여기서 한 번만 생성하여 필터가 일관되게 적용됩니다.
"""
import json as _json
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = _json.loads
