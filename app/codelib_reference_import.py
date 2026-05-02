"""
코드 갤러리(ABAPCode) 한 건 → 참고 코드 JSON(reference_code_payload) 변환.
관리자만 사용하는 가져오기 API에서 호출합니다.
"""
from __future__ import annotations

import json

from . import models
from .rfp_reference_code import normalize_reference_code_payload
from .routers.codelib_router import _parse_upload_sections_for_edit


def _empty_slot() -> dict:
    return {
        "program_id": "",
        "transaction_code": "",
        "title": "",
        "sap_modules": [],
        "dev_types": [],
        "sections": [{"type": "메인 프로그램", "name": "", "code": ""}],
    }


def build_reference_payload_dict_from_abap_code(code: models.ABAPCode) -> dict | None:
    """
    갤러리 1건을 참고코드 스키마(v1, 슬롯 3)로 변환.
    실패(용량 초과·내용 없음) 시 None.
    """
    sections = _parse_upload_sections_for_edit((code.source_code or "").replace("\r\n", "\n"))
    if len(sections) > 50:
        sections = sections[:50]
    sm = [x.strip() for x in (code.sap_modules or "").split(",") if x.strip()][:3]
    dt = [x.strip() for x in (code.dev_types or "").split(",") if x.strip()][:3]
    slot0 = {
        "program_id": (code.program_id or "").strip()[:40],
        "transaction_code": (code.transaction_code or "").strip()[:20],
        "title": (code.title or "").strip()[:200],
        "sap_modules": sm,
        "dev_types": dt,
        "sections": sections if sections else [{"type": "메인 프로그램", "name": "", "code": ""}],
    }
    data = {
        "v": 1,
        "slots": [slot0, _empty_slot(), _empty_slot()],
        "visibleSlotCount": 1,
    }
    raw = json.dumps(data, ensure_ascii=False)
    try:
        norm = normalize_reference_code_payload(raw)
    except ValueError:
        return None
    if not norm:
        return None
    return json.loads(norm)
