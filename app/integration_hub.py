"""연동 개발 통합 상세 — URL phase 쿼리 (신규 개발 RFP 허브와 동일한 phase 이름)."""

from __future__ import annotations

_INTEGRATION_HUB_PHASES = frozenset({"request", "interview", "proposal", "fs", "devcode"})


def normalize_integration_hub_phase(raw: str | None) -> str:
    s = (raw or "request").strip().lower()
    return s if s in _INTEGRATION_HUB_PHASES else "request"


def integration_hub_url(req_id: int, phase: str, *, view_summary: bool = False) -> str:
    p = normalize_integration_hub_phase(phase)
    url = f"/integration/{req_id}?phase={p}"
    if view_summary and p == "interview":
        url += "&view=summary"
    return url
