"""Hub floating panel: requester ↔ consultant offer inquiry (distinct from AI chat)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from .integration_hub import integration_hub_url, normalize_integration_hub_phase
from .offer_inquiry_service import offer_inquiry_needs_consultant_reply, sanitize_console_readonly_return_url
from .rfp_hub import normalize_rfp_hub_phase, rfp_hub_url

_ABAP_HUB_PHASES = frozenset(
    {"request", "analysis", "proposal", "fs", "devcode", "asbuilt", "settlement"}
)

MEMBER_INQUIRY_FLOAT_HASH = "offer-member-inquiry"
MEMBER_INQUIRY_FLOAT_ID = "offer-member-inquiry-float"


def normalize_abap_hub_phase(raw: str | None) -> str:
    s = (raw or "proposal").strip().lower()
    return s if s in _ABAP_HUB_PHASES else "proposal"


def _pick_default_offer_id(
    offers: list,
    *,
    inquiries_by_offer_id: dict[int, list],
    query_offer_raw: str | None,
) -> int | None:
    if not offers:
        return None
    valid_ids = {int(o.id) for o in offers}
    q = (query_offer_raw or "").strip()
    if q.isdigit() and int(q) in valid_ids:
        return int(q)
    for o in offers:
        if (getattr(o, "status", None) or "").strip() == "matched":
            return int(o.id)
    for o in offers:
        if inquiries_by_offer_id.get(int(o.id)):
            return int(o.id)
    return int(offers[0].id)


def build_offer_member_inquiry_ctx(
    db: Session,
    *,
    user,
    owner_user_id: int,
    offers: list,
    inquiries_by_offer_id: dict[int, list],
    can_inquire: bool,
    readonly_console: bool,
    hub_phase: str,
    hub_readonly_return_url: str | None,
    query_params: Any,
) -> dict[str, Any] | None:
    """Template ctx for `offer_member_inquiry` float, or None when hidden."""
    if not user:
        return None

    is_owner = int(user.id) == int(owner_user_id)
    is_admin = bool(getattr(user, "is_admin", False))
    is_consultant = bool(getattr(user, "is_consultant", False))

    active_offers = [o for o in offers if (getattr(o, "status", None) or "").strip() != "withdrawn"]
    consultant_offers = [
        o
        for o in offers
        if int(getattr(o, "consultant_user_id", 0) or 0) == int(user.id)
        and (getattr(o, "status", None) or "").strip() in ("offered", "matched")
    ]

    mode: str | None = None
    selectable: list = []
    can_compose = False

    # 요청 Console 읽기 전용: 요청자 발송만 막고, 매칭 컨·관리자는 플로팅 유지.
    owner_may_compose = is_owner and can_inquire and not readonly_console

    if owner_may_compose and active_offers:
        mode = "owner"
        selectable = list(active_offers)
        can_compose = True
    elif is_consultant and consultant_offers:
        mode = "consultant"
        selectable = list(consultant_offers)
        can_compose = True
    elif is_admin and offers:
        mode = "viewer"
        with_history = [o for o in offers if inquiries_by_offer_id.get(int(o.id))]
        selectable = with_history if with_history else list(offers)
        can_compose = False
    else:
        return None

    if not selectable:
        return None

    default_offer_id = _pick_default_offer_id(
        selectable,
        inquiries_by_offer_id=inquiries_by_offer_id,
        query_offer_raw=(query_params.get("offer_inquiry_offer") or "").strip() or None,
    )

    pending_reply = False
    if mode == "consultant":
        for o in selectable:
            if offer_inquiry_needs_consultant_reply(db, int(o.id)):
                pending_reply = True
                break

    total_messages = sum(len(inquiries_by_offer_id.get(int(o.id), [])) for o in selectable)

    err = (query_params.get("offer_inquiry_err") or "").strip()
    ok = (query_params.get("offer_inquiry_ok") or "").strip() == "1"
    reply_err = (query_params.get("offer_inquiry_reply_err") or "").strip()
    reply_ok = (query_params.get("offer_inquiry_reply_ok") or "").strip() == "1"

    return {
        "enabled": True,
        "float_id": MEMBER_INQUIRY_FLOAT_ID,
        "mode": mode,
        "selectable_offers": selectable,
        "default_offer_id": default_offer_id,
        "can_compose": can_compose,
        "pending_reply": pending_reply,
        "total_messages": total_messages,
        "hub_phase": hub_phase,
        "hub_readonly_return_url": hub_readonly_return_url,
        "show_offer_picker": len(selectable) > 1 and mode in ("owner", "viewer", "consultant"),
        "err": err,
        "ok": ok,
        "reply_err": reply_err,
        "reply_ok": reply_ok,
        "size_key": "offer-member-inquiry-size",
    }


def _append_query(base: str, params: dict[str, str]) -> str:
    if not params:
        return base
    hash_part = ""
    path = base
    if "#" in base:
        path, frag = base.split("#", 1)
        hash_part = "#" + frag
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urlencode(params)}{hash_part}"


def member_inquiry_redirect_url(
    *,
    request_kind: str,
    request_id: int,
    hub_phase: str | None = None,
    console_readonly: bool = False,
    return_hub: str | None = None,
    offer_id: int | None = None,
    **flash: str,
) -> str:
    """Redirect back to hub on current phase with float auto-open hints."""
    kind = (request_kind or "").strip().lower()
    params: dict[str, str] = {k: v for k, v in flash.items() if v}
    if offer_id is not None:
        params["offer_inquiry_offer"] = str(int(offer_id))

    safe = sanitize_console_readonly_return_url(return_hub)
    if safe:
        url = _append_query(safe, params)
        if kind != "analysis":
            url += f"#{MEMBER_INQUIRY_FLOAT_HASH}"
        return url

    if kind == "rfp":
        phase = normalize_rfp_hub_phase(hub_phase)
        base = rfp_hub_url(int(request_id), phase)
        return _append_query(base, params) + f"#{MEMBER_INQUIRY_FLOAT_HASH}"

    if kind == "integration":
        phase = normalize_integration_hub_phase(hub_phase)
        base = integration_hub_url(int(request_id), phase)
        return _append_query(base, params) + f"#{MEMBER_INQUIRY_FLOAT_HASH}"

    if kind == "analysis":
        phase = normalize_abap_hub_phase(hub_phase)
        path = (
            f"/abap-analysis/{int(request_id)}/console-readonly"
            if console_readonly
            else f"/abap-analysis/{int(request_id)}"
        )
        phase_params = {"phase": phase, **params}
        frag = f"abap-phase-{phase}"
        return f"{path}?{urlencode(phase_params)}#{frag}"

    return "/"
