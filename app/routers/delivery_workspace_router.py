"""납품 ABAP 구현 보완 작업실 — 독립 경로(공식 납품 payload 비변경)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import auth
from ..ai_usage_billing import delivery_job_billing_user_id, wallet_preflight_for_delivery_stage
from ..database import get_db
from ..delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from ..delivery_workspace import (
    apply_slot_source,
    build_workspace_zip_bytes,
    clear_pending_suggestion,
    get_pending_suggestion,
    get_working_package,
    load_request_row,
    normalize_request_kind,
    package_has_slots,
    set_pending_suggestion,
    slots_detail_for_ui,
)
from ..delivery_workspace_access import user_can_use_delivery_workspace
from ..delivery_workspace_display import workspace_page_header
from ..delivery_workspace_ai import STAGE_DELIVERY_WORKSPACE_FIX, suggest_slot_fix
from ..delivery_workspace_context import build_peer_sources_context
from ..delivery_workspace_diff import diff_panel_html
from ..delivery_workspace_validation import (
    cross_slot_fix_hints,
    main_slot_filenames,
    slot_is_include_like,
    suggestion_defers_fix_elsewhere,
    validate_suggested_against_original,
)
from ..rfp_download_names import content_disposition_attachment
from ..templates_config import templates

router = APIRouter(tags=["delivery-workspace"])


def _safe_return_to_path(raw: str | None) -> str | None:
    """오픈 리다이렉트 방지: 동일 사이트 상대 경로만."""
    s = (raw or "").strip()
    if not s.startswith("/") or s.startswith("//") or ".." in s or "\n" in s or "\r" in s:
        return None
    return s


def _hub_return_url(kind: str, row: Any, user, return_to: str | None) -> str:
    back = _safe_return_to_path(return_to)
    if back:
        return back
    owner = int(getattr(row, "user_id", 0) or 0)
    if kind == KIND_RFP:
        from ..rfp_hub import rfp_hub_url

        return rfp_hub_url(int(row.id), "devcode") + "#rfp-phase-devcode"
    if kind == KIND_INTEGRATION:
        from ..integration_hub import integration_hub_url

        return integration_hub_url(int(row.id), "devcode") + "#int-phase-devcode"
    from ..request_hub_access import menu_abap_detail_url

    return menu_abap_detail_url(user=user, owner_user_id=owner, request_id=int(row.id)) + "#abap-phase-devcode"


def _workspace_path(kind: str, request_id: int) -> str:
    return f"/delivery/{kind}/{int(request_id)}/workspace"


def _workspace_redirect(
    kind: str, request_id: int, *, return_to: str | None = None, **query: str | int
) -> str:
    base = _workspace_path(kind, request_id)
    parts: list[str] = []
    if return_to:
        parts.append("return_to=" + quote(return_to, safe=""))
    for k, v in query.items():
        if v is None or v == "":
            continue
        parts.append(f"{k}={quote(str(v), safe='')}")
    if not parts:
        return base
    return base + "?" + "&".join(parts)


def _require_access(db: Session, user, row: Any, kind: str) -> None:
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    if not user_can_use_delivery_workspace(
        db,
        user,
        request_kind=kind,
        request_id=int(row.id),
        owner_user_id=int(row.user_id),
        entity=row,
    ):
        raise HTTPException(status_code=403, detail="forbidden")


def _slot_source(pkg: dict, index: int) -> str:
    slots = pkg.get("slots") or []
    if index < 0 or index >= len(slots):
        return ""
    sl = slots[index]
    if not isinstance(sl, dict):
        return ""
    return (sl.get("source") or "").strip()


@router.get("/delivery/{kind}/{request_id}/workspace", response_class=HTMLResponse)
def delivery_workspace_page(
    kind: str,
    request_id: int,
    request: Request,
    return_to: str | None = None,
    ws_err: str | None = None,
    ws_ok: str | None = None,
    ws_warn: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)
    pkg = get_working_package(db, row, norm)
    if not pkg or not package_has_slots(pkg, norm):
        raise HTTPException(status_code=404, detail="no_package")

    slot_idx = 0
    try:
        raw_idx = request.query_params.get("slot")
        if raw_idx is not None:
            slot_idx = max(0, int(raw_idx))
    except (TypeError, ValueError):
        slot_idx = 0
    slot_details = slots_detail_for_ui(pkg)
    if slot_details and slot_idx >= len(slot_details):
        slot_idx = 0

    pending = get_pending_suggestion(pkg, slot_idx)
    suggested_source = ((pending or {}).get("suggested_source") or "").strip()
    last_se38 = ((pending or {}).get("se38_error") or "").strip()
    peer_count_sess = int((pending or {}).get("peer_count") or 0)
    fix_elsewhere_target = ((pending or {}).get("fix_elsewhere_target") or "").strip() or None
    fix_elsewhere_reason = ((pending or {}).get("fix_elsewhere_reason") or "").strip() or None

    ws_ok_val = (ws_ok or "").strip()
    if ws_ok_val in ("suggested", "suggested_elsewhere") and not suggested_source:
        ws_ok_val = ""
        ws_err = ws_err or "suggestion_lost"

    slots_raw = pkg.get("slots") or []
    cross_hints: tuple[str, ...] = ()
    if last_se38 and slot_details:
        cross_hints = cross_slot_fix_hints(last_se38, slots_raw, active_index=slot_idx)
    main_names = list(main_slot_filenames(slots_raw))

    ctx = {
        "request": request,
        "user": user,
        "request_kind": norm,
        "entity": row,
        "request_id": int(row.id),
        "return_url": _hub_return_url(norm, row, user, return_to),
        "workspace_base": _workspace_path(norm, int(row.id)),
        "return_to": return_to,
        "slot_details": slot_details,
        "slot_index": slot_idx,
        "program_id": (pkg.get("program_id") or "").strip(),
        "ws_err": (ws_err or "").strip() or None,
        "ws_ok": ws_ok_val or None,
        "ws_warn": (ws_warn or "").strip() or None,
        "suggested_source": suggested_source,
        "last_se38_error": last_se38,
        "cross_slot_hints": list(cross_hints),
        "main_slot_filenames": main_names,
        "fix_elsewhere_target": fix_elsewhere_target,
        "fix_elsewhere_reason": fix_elsewhere_reason,
        "suggest_peer_slot_count": peer_count_sess,
        "sap_version": (getattr(row, "sap_system_version", None) or "").strip(),
        **workspace_page_header(row, norm),
    }
    return templates.TemplateResponse(request, "delivery_workspace.html", ctx)


@router.post("/delivery/{kind}/{request_id}/workspace/diff-preview")
def delivery_workspace_diff_preview(
    kind: str,
    request_id: int,
    original_source: str = Form(""),
    suggested_source: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)
    html = diff_panel_html(original_source or "", suggested_source or "")
    return JSONResponse({"html": html})


@router.post("/delivery/{kind}/{request_id}/workspace/slots/{slot_index}/save")
def delivery_workspace_save_slot(
    kind: str,
    request_id: int,
    slot_index: int,
    source: str = Form(""),
    return_to: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)
    try:
        apply_slot_source(db, row, norm, int(slot_index), source or "")
        db.commit()
    except (IndexError, ValueError):
        db.rollback()
        url = _workspace_redirect(norm, int(row.id), return_to=return_to, ws_err="invalid_slot")
        return RedirectResponse(url=url, status_code=303)
    url = _workspace_redirect(
        norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_ok="saved"
    )
    return RedirectResponse(url=url, status_code=303)


@router.post("/delivery/{kind}/{request_id}/workspace/suggest-fix")
def delivery_workspace_suggest_fix(
    request: Request,
    kind: str,
    request_id: int,
    slot_index: int = Form(0),
    se38_error: str = Form(""),
    return_to: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)

    billing_uid = delivery_job_billing_user_id(int(user.id))
    pre = wallet_preflight_for_delivery_stage(db, user, stage=STAGE_DELIVERY_WORKSPACE_FIX)
    if pre:
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_err=pre
            ),
            status_code=303,
        )

    pkg = get_working_package(db, row, norm)
    if not pkg:
        return RedirectResponse(
            url=_workspace_redirect(norm, int(row.id), return_to=return_to, ws_err="no_package"),
            status_code=303,
        )
    idx = int(slot_index)
    slots = pkg.get("slots") or []
    if idx < 0 or idx >= len(slots) or not isinstance(slots[idx], dict):
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=idx, ws_err="invalid_slot"
            ),
            status_code=303,
        )
    sl = slots[idx]
    slot_role = (sl.get("role") or "other").strip()
    current_src = _slot_source(pkg, idx)
    _, peer_count = build_peer_sources_context(slots, active_index=idx)
    suggested, err = suggest_slot_fix(
        billing_user_id=billing_uid,
        request_kind=norm,
        request_id=int(row.id),
        slot_filename=(sl.get("filename") or f"slot_{idx + 1}.abap").strip(),
        slot_role=slot_role,
        current_source=current_src,
        se38_error=se38_error,
        sap_version_hint=(getattr(row, "sap_system_version", None) or "").strip(),
        program_id=(pkg.get("program_id") or "").strip(),
        package_slots=slots,
        active_slot_index=idx,
        main_slot_filenames=list(main_slot_filenames(slots)),
        active_slot_is_include_like=slot_is_include_like(slot_role),
    )
    if err:
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=idx, ws_err=err
            ),
            status_code=303,
        )
    db.commit()
    deferred, fix_target, fix_reason = suggestion_defers_fix_elsewhere(
        suggested, current_src
    )
    ws_ok_val = "suggested_elsewhere" if deferred else "suggested"
    try:
        set_pending_suggestion(
            db,
            row,
            norm,
            idx,
            suggested_source=suggested,
            se38_error=se38_error,
            fix_elsewhere_target=fix_target if deferred else None,
            fix_elsewhere_reason=fix_reason if deferred else None,
            peer_count=peer_count,
        )
        db.commit()
    except ValueError:
        db.rollback()
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=idx, ws_err="no_package"
            ),
            status_code=303,
        )
    return RedirectResponse(
        url=_workspace_redirect(
            norm, int(row.id), return_to=return_to, slot=idx, ws_ok=ws_ok_val
        ),
        status_code=303,
    )


@router.post("/delivery/{kind}/{request_id}/workspace/slots/{slot_index}/apply")
def delivery_workspace_apply_suggestion(
    request: Request,
    kind: str,
    request_id: int,
    slot_index: int,
    suggested_source: str = Form(""),
    force_apply: str | None = Form(None),
    return_to: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)
    if not (suggested_source or "").strip():
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_err="empty"
            ),
            status_code=303,
        )
    pkg = get_working_package(db, row, norm)
    if not pkg:
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_err="no_package"
            ),
            status_code=303,
        )
    idx = int(slot_index)
    slots = pkg.get("slots") or []
    slot_role = "other"
    if 0 <= idx < len(slots) and isinstance(slots[idx], dict):
        slot_role = (slots[idx].get("role") or "other").strip()
    original = _slot_source(pkg, idx)
    validation = validate_suggested_against_original(
        original, suggested_source, slot_role=slot_role
    )
    forced = (force_apply or "").strip().lower() in ("1", "true", "yes", "on")
    deferred, _, _ = suggestion_defers_fix_elsewhere(suggested_source, original)
    if deferred and not forced:
        return RedirectResponse(
            url=_workspace_redirect(
                norm,
                int(row.id),
                return_to=return_to,
                slot=idx,
                ws_warn="fix_elsewhere",
            ),
            status_code=303,
        )
    if not validation.ok and not forced:
        warn_code = validation.warn_codes[0] if validation.warn_codes else "source_shorter"
        return RedirectResponse(
            url=_workspace_redirect(
                norm,
                int(row.id),
                return_to=return_to,
                slot=idx,
                ws_warn=warn_code,
            ),
            status_code=303,
        )
    try:
        apply_slot_source(db, row, norm, int(slot_index), suggested_source)
        clear_pending_suggestion(db, row, norm)
        db.commit()
    except (IndexError, ValueError):
        db.rollback()
        return RedirectResponse(
            url=_workspace_redirect(
                norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_err="invalid_slot"
            ),
            status_code=303,
        )
    return RedirectResponse(
        url=_workspace_redirect(
            norm, int(row.id), return_to=return_to, slot=int(slot_index), ws_ok="applied"
        ),
        status_code=303,
    )


@router.get("/delivery/{kind}/{request_id}/workspace/build-zip")
def delivery_workspace_build_zip(
    kind: str,
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth.get_current_user),
):
    norm = normalize_request_kind(kind)
    if not norm:
        raise HTTPException(status_code=404, detail="not_found")
    row = load_request_row(db, request_kind=norm, request_id=request_id)
    _require_access(db, user, row, norm)
    pkg = get_working_package(db, row, norm)
    if not pkg:
        raise HTTPException(status_code=404, detail="no_package")
    data = build_workspace_zip_bytes(row, pkg, norm)
    fn = f"workspace_{norm}_{int(row.id)}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition_attachment(fn)},
    )
