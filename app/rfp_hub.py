"""신규 개발(RFP) 통합 상세 페이지 — URL phase 쿼리."""

from __future__ import annotations

_RFP_HUB_PHASES = frozenset({"request", "interview", "proposal", "fs", "devcode"})


def normalize_rfp_hub_phase(raw: str | None) -> str:
    s = (raw or "request").strip().lower()
    return s if s in _RFP_HUB_PHASES else "request"


def rfp_hub_url(rfp_id: int, phase: str, *, view_summary: bool = False) -> str:
    p = normalize_rfp_hub_phase(phase)
    url = f"/rfp/{rfp_id}?phase={p}"
    if view_summary and p == "interview":
        url += "&view=summary"
    return url
