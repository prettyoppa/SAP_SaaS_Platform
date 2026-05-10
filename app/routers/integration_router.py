"""SAP 연동 개발 요청 라우터 (VBA, Python, 배치, API 등)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from .. import models, auth
from ..abap_followup_chat import MAX_USER_TURNS_PER_REQUEST as INT_CHAT_MAX_USER
from .abap_analysis_router import _pair_abap_followup_turns as _pair_integration_followup_turns
from ..attachment_context import build_attachment_llm_digest
from ..database import get_db
from ..rfp_reference_code import normalize_reference_code_payload, reference_code_program_groups_for_tabs
from ..menu_landing import (
    DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO,
    TILE_ORDER_WITH_ALL,
    VALID_URL_BUCKETS,
    abap_analysis_menu_aggregate,
    abap_analysis_menu_bucket,
    filtered_abap_analysis_menu_rows,
    filtered_integration_menu_rows,
    integration_menu_bucket,
    integration_menu_aggregate,
    menu_landing_preset_params,
    menu_landing_url,
    parse_slashed_date,
    standard_menu_bucket_meta,
    user_proposal_pending_offer_badges,
)
from ..rfp_landing import (
    DEFAULT_SERVICE_ABAP_INTRO_MD_KO,
    filtered_rfp_list_for_landing,
    rfp_landing_aggregate,
    rfp_landing_bucket,
)
from ..devtype_catalog import (
    active_integration_impl_devtypes,
    integration_impl_allowed_codes,
    integration_impl_labels_map,
)
from ..offer_inquiry_service import (
    inquiries_by_offer_id,
    pending_inquiry_reply_offer_ids_for_consultant,
    public_request_url,
    send_consultant_matched_first_inquiry_to_owner,
    send_consultant_offer_inquiry_reply,
    send_offer_inquiry_from_owner,
)
from ..code_asset_access import user_may_copy_download_request_assets
from ..request_hub_access import apply_integration_hub_read_access, consultant_has_request_offer
from ..request_offer_visibility import visible_request_offers_for_viewer
from ..templates_config import layout_template_from_embed_query, templates
from ..writing_guides_service import get_writing_guides_by_lang_bundle
from ..paid_tier import user_can_operate_delivery
from ..integration_followup_chat import (
    generate_integration_followup_reply,
    integration_request_llm_summary,
    validate_integration_user_message,
)
from ..agent_display import wrap_unbracketed_agent_names
from ..integration_hub import integration_hub_url, normalize_integration_hub_phase
from ..integration_interview_service import serve_integration_interview_workspace
from ..routers.interview_router import _markdown_to_html, _messages_to_list
from .rfp_router import (
    MAX_RFP_ATTACHMENTS,
    _build_attachment_entries_from_uploads,
    _get_modules_devtypes,
    _remove_stored_file,
    duplicate_attachment_entries,
    r2_storage,
)

router = APIRouter()


def _integration_impl_ui_ctx(db: Session) -> dict:
    """연동 구현 형태: 폼 칩(순서) + 배지용 코드→라벨 맵 + 작성 가이드 맵."""
    return {
        "integration_impl_devtypes": active_integration_impl_devtypes(db),
        "impl_labels": integration_impl_labels_map(db),
        "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
    }


def _attachment_entries(ir: models.IntegrationRequest) -> list[dict]:
    if not ir.attachments_json:
        return []
    try:
        data = json.loads(ir.attachments_json)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("path")]
    except Exception:
        pass
    return []


def _set_attachments(ir: models.IntegrationRequest, entries: list[dict]) -> None:
    if not entries:
        ir.attachments_json = None
        return
    ir.attachments_json = json.dumps(entries, ensure_ascii=False)


def _integration_offer_rows(db: Session, req_id: int) -> list[models.RequestOffer]:
    return (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.request_kind == "integration",
            models.RequestOffer.request_id == req_id,
        )
        .order_by(models.RequestOffer.created_at.desc())
        .all()
    )


_REQ_CONSOLE_KINDS = ("all", "abap", "analysis", "integration", "offer", "matching")
_REQ_CONSOLE_BUCKETS = ("all", "delivery", "proposal", "analysis", "in_progress", "draft")


def _request_no(prefix: str, v: int) -> str:
    return f"{prefix}-{int(v)}"


def _console_unified_hub_embed_phase(bucket: str) -> str:
    """Console iframe 기본 단계: 목록 버킷과 맞춰 제안/오퍼·인터뷰 영역이 보이도록."""
    b = (bucket or "").strip().lower()
    if b in ("proposal", "delivery"):
        return "proposal"
    if b == "analysis":
        return "interview"
    return "request"


def _console_abap_preview_suffix(bucket: str) -> str:
    b = (bucket or "").strip().lower()
    if b in ("proposal", "delivery"):
        return "#abap-phase-offers"
    return ""


def _console_row_for_offer_target(db: Session, kind: str, req_id: int) -> dict[str, Any] | None:
    k = (kind or "").strip().lower()
    if k == "rfp":
        row = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.owner))
            .filter(models.RFP.id == req_id)
            .first()
        )
        if not row:
            return None
        return _console_row_from_rfp(row)
    if k == "analysis":
        row = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.owner))
            .filter(models.AbapAnalysisRequest.id == req_id)
            .first()
        )
        if not row:
            return None
        return _console_row_from_analysis(row)
    if k == "integration":
        row = (
            db.query(models.IntegrationRequest)
            .options(joinedload(models.IntegrationRequest.owner))
            .filter(models.IntegrationRequest.id == req_id)
            .first()
        )
        if not row:
            return None
        return _console_row_from_integration(row)
    return None


def _console_rows_from_offers(db: Session, consultant_user_id: int, *, matched_only: bool) -> list[dict[str, Any]]:
    st = "matched" if matched_only else "offered"
    offers = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.consultant_user_id == consultant_user_id,
            models.RequestOffer.status == st,
        )
        .order_by(models.RequestOffer.created_at.desc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for of in offers:
        row = _console_row_for_offer_target(db, of.request_kind, of.request_id)
        if not row:
            continue
        row["offer_status"] = of.status
        row["offer_id"] = of.id
        out.append(row)
    return out


def _offered_request_id_set(
    db: Session, request_kind: str, ids: list[int], *, pending_only: bool = False
) -> set[int]:
    if not ids:
        return set()
    q = db.query(models.RequestOffer.request_id).filter(
        models.RequestOffer.request_kind == request_kind,
        models.RequestOffer.request_id.in_(ids),
    )
    if pending_only:
        q = q.filter(models.RequestOffer.status == "offered")
    rows = q.distinct().all()
    return {int(r[0]) for r in rows if r and r[0] is not None}


def _consultant_active_offer_sel_keys(db: Session, consultant_user_id: int) -> set[str]:
    keys: set[str] = set()
    offers = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.consultant_user_id == consultant_user_id,
            models.RequestOffer.status == "offered",
        )
        .all()
    )
    for of in offers:
        if of.request_kind == "rfp":
            keys.add(f"rfp:{of.request_id}")
        elif of.request_kind == "analysis":
            keys.add(f"ana:{of.request_id}")
        elif of.request_kind == "integration":
            keys.add(f"int:{of.request_id}")
    return keys


def _request_console_return_location(
    *,
    return_kind: str,
    return_bucket: str,
    return_sel: str,
    return_title: str,
    return_date_from: str,
    return_date_to: str,
) -> str:
    rk = (return_kind or "all").strip().lower()
    if rk not in _REQ_CONSOLE_KINDS:
        rk = "all"
    rb = (return_bucket or "all").strip().lower()
    if rb not in _REQ_CONSOLE_BUCKETS:
        rb = "all"
    params: dict[str, str] = {"kind": rk, "bucket": rb}
    sel = (return_sel or "").strip()
    if sel:
        params["sel"] = sel
    tt = (return_title or "").strip()
    if tt:
        params["title"] = tt
    df = (return_date_from or "").strip()
    if df:
        params["date_from"] = df
    dto = (return_date_to or "").strip()
    if dto:
        params["date_to"] = dto
    return "/request-console?" + urlencode(params)


def _console_sel_key_to_offer_lookup_key(sel_key: str) -> tuple[str, int] | None:
    sk = (sel_key or "").strip()
    if sk.startswith("rfp:"):
        try:
            return ("rfp", int(sk.split(":", 1)[1]))
        except (ValueError, IndexError):
            return None
    if sk.startswith("ana:"):
        try:
            return ("analysis", int(sk.split(":", 1)[1]))
        except (ValueError, IndexError):
            return None
    if sk.startswith("int:"):
        try:
            return ("integration", int(sk.split(":", 1)[1]))
        except (ValueError, IndexError):
            return None
    return None


def _console_public_detail_url(request: Request, req_kind: str, req_id: int) -> str:
    if req_kind == "rfp":
        return public_request_url(request, f"/rfp/{req_id}?phase=proposal")
    if req_kind == "analysis":
        return public_request_url(request, f"/abap-analysis/{req_id}#abap-phase-offers")
    if req_kind == "integration":
        return public_request_url(request, f"/integration/{req_id}?phase=proposal")
    return public_request_url(request, "/")


def _console_request_title_and_owner(
    db: Session, req_kind: str, req_id: int
) -> tuple[models.User | None, str]:
    if req_kind == "rfp":
        row = (
            db.query(models.RFP)
            .options(joinedload(models.RFP.owner))
            .filter(models.RFP.id == req_id)
            .first()
        )
        if not row:
            return None, ""
        title = (row.title or "").strip() or f"RFP #{req_id}"
        return row.owner, title
    if req_kind == "analysis":
        row = (
            db.query(models.AbapAnalysisRequest)
            .options(joinedload(models.AbapAnalysisRequest.owner))
            .filter(models.AbapAnalysisRequest.id == req_id)
            .first()
        )
        if not row:
            return None, ""
        title = (row.title or "").strip() or f"분석 #{req_id}"
        return row.owner, title
    if req_kind == "integration":
        row = (
            db.query(models.IntegrationRequest)
            .options(joinedload(models.IntegrationRequest.owner))
            .filter(models.IntegrationRequest.id == req_id)
            .first()
        )
        if not row:
            return None, ""
        title = (row.title or "").strip() or f"연동 #{req_id}"
        return row.owner, title
    return None, ""


def _console_row_from_rfp(r: models.RFP) -> dict[str, Any]:
    return {
        "sel_key": f"rfp:{r.id}",
        "entity_id": r.id,
        "kind": "abap",
        "kind_ko": "신규개발",
        "request_no": _request_no("RFP", r.id),
        "title": (r.title or "").strip() or f"요청 {_request_no('RFP', r.id)}",
        "bucket": rfp_landing_bucket(r),
        "created_at": r.created_at,
        "owner_name": getattr(getattr(r, "owner", None), "full_name", "") or "",
        "owner_company": getattr(getattr(r, "owner", None), "company", "") or "",
        "detail_href": f"/rfp/{r.id}",
        "preview_href": (
            f"/rfp/{r.id}/console-readonly?embed=1&phase={_console_unified_hub_embed_phase(rfp_landing_bucket(r))}"
        ),
        "summary": (r.description or "").strip(),
    }


def _console_row_from_analysis(row: models.AbapAnalysisRequest) -> dict[str, Any]:
    return {
        "sel_key": f"ana:{row.id}",
        "entity_id": row.id,
        "kind": "analysis",
        "kind_ko": "분석개선",
        "request_no": _request_no("ANA", row.id),
        "title": (row.title or "").strip() or f"요청 {_request_no('ANA', row.id)}",
        "bucket": abap_analysis_menu_bucket(row),
        "created_at": row.created_at,
        "owner_name": getattr(getattr(row, "owner", None), "full_name", "") or "",
        "owner_company": getattr(getattr(row, "owner", None), "company", "") or "",
        "detail_href": f"/abap-analysis/{row.id}",
        "preview_href": (
            f"/abap-analysis/{row.id}/console-readonly?embed=1{_console_abap_preview_suffix(abap_analysis_menu_bucket(row))}"
        ),
        "summary": (row.requirement_text or "").strip(),
    }


def _console_row_from_integration(ir: models.IntegrationRequest) -> dict[str, Any]:
    return {
        "sel_key": f"int:{ir.id}",
        "entity_id": ir.id,
        "kind": "integration",
        "kind_ko": "연동개발",
        "request_no": _request_no("INT", ir.id),
        "title": (ir.title or "").strip() or f"요청 {_request_no('INT', ir.id)}",
        "bucket": integration_menu_bucket(ir),
        "created_at": ir.created_at,
        "owner_name": getattr(getattr(ir, "owner", None), "full_name", "") or "",
        "owner_company": getattr(getattr(ir, "owner", None), "company", "") or "",
        "detail_href": f"/integration/{ir.id}",
        "preview_href": (
            f"/integration/{ir.id}/console-readonly?embed=1&phase={_console_unified_hub_embed_phase(integration_menu_bucket(ir))}"
        ),
        "summary": (ir.description or "").strip(),
    }


@router.get("/request-console", response_class=HTMLResponse)
def request_console_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/request-console", status_code=302)
    if not (user.is_admin or user.is_consultant):
        return RedirectResponse(url="/", status_code=302)

    kind = (request.query_params.get("kind") or "all").strip().lower()
    if kind not in _REQ_CONSOLE_KINDS:
        kind = "all"
    bucket = (request.query_params.get("bucket") or "all").strip().lower()
    if bucket not in _REQ_CONSOLE_BUCKETS:
        bucket = "all"

    title_search = (request.query_params.get("title") or "").strip() or None
    date_from_raw = (request.query_params.get("date_from") or "").strip() or None
    date_to_raw = (request.query_params.get("date_to") or "").strip() or None
    date_from_dt = parse_slashed_date(date_from_raw)
    date_to_dt = parse_slashed_date(date_to_raw)

    rfp_counts, _ = rfp_landing_aggregate(db, admin=True, user_id=user.id)
    ana_counts, _ = abap_analysis_menu_aggregate(db, admin=True, user_id=user.id)
    int_counts, _ = integration_menu_aggregate(db, admin=True, user_id=user.id)

    def _count_pack(d: dict[str, int]) -> dict[str, int]:
        return {"all": int(sum(d.values())), **{k: int(d.get(k, 0)) for k in _REQ_CONSOLE_BUCKETS if k != "all"}}

    counts_by_kind = {
        "abap": _count_pack(rfp_counts),
        "analysis": _count_pack(ana_counts),
        "integration": _count_pack(int_counts),
    }
    counts_by_kind["all"] = {
        k: counts_by_kind["abap"].get(k, 0) + counts_by_kind["analysis"].get(k, 0) + counts_by_kind["integration"].get(k, 0)
        for k in _REQ_CONSOLE_BUCKETS
    }
    offered_rows = _console_rows_from_offers(db, user.id, matched_only=False)
    matched_rows = _console_rows_from_offers(db, user.id, matched_only=True)
    counts_by_kind["offer"] = _count_pack(
        {
            "delivery": sum(1 for r in offered_rows if r.get("bucket") == "delivery"),
            "proposal": sum(1 for r in offered_rows if r.get("bucket") == "proposal"),
            "analysis": sum(1 for r in offered_rows if r.get("bucket") == "analysis"),
            "in_progress": sum(1 for r in offered_rows if r.get("bucket") == "in_progress"),
            "draft": sum(1 for r in offered_rows if r.get("bucket") == "draft"),
        }
    )
    counts_by_kind["matching"] = _count_pack(
        {
            "delivery": sum(1 for r in matched_rows if r.get("bucket") == "delivery"),
            "proposal": sum(1 for r in matched_rows if r.get("bucket") == "proposal"),
            "analysis": sum(1 for r in matched_rows if r.get("bucket") == "analysis"),
            "in_progress": sum(1 for r in matched_rows if r.get("bucket") == "in_progress"),
            "draft": sum(1 for r in matched_rows if r.get("bucket") == "draft"),
        }
    )

    rows: list[dict[str, Any]] = []
    if kind in ("all", "abap"):
        rfps = filtered_rfp_list_for_landing(
            db,
            admin=True,
            user_id=user.id,
            bucket=bucket,
            title_q=title_search,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
        rows.extend(_console_row_from_rfp(r) for r in rfps)
    if kind in ("all", "analysis"):
        analyses = filtered_abap_analysis_menu_rows(
            db,
            admin=True,
            user_id=user.id,
            bucket=bucket,
            title_q=title_search,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
        rows.extend(_console_row_from_analysis(r) for r in analyses)
    if kind in ("all", "integration"):
        irs = filtered_integration_menu_rows(
            db,
            admin=True,
            user_id=user.id,
            bucket=bucket,
            title_q=title_search,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
        rows.extend(_console_row_from_integration(r) for r in irs)
    if kind == "offer":
        rows = offered_rows
    if kind == "matching":
        rows = matched_rows

    rows.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    active_offer_keys = _consultant_active_offer_sel_keys(db, user.id)
    for row in rows:
        row["consultant_has_offered"] = row.get("sel_key") in active_offer_keys

    pending_inquiry_offer_ids: set[int] = set()
    consultant_offer_meta: dict[tuple[str, int], tuple[int, str]] = {}
    if getattr(user, "is_consultant", False):
        pending_inquiry_offer_ids = pending_inquiry_reply_offer_ids_for_consultant(db, user.id)
        for co in (
            db.query(models.RequestOffer)
            .filter(
                models.RequestOffer.consultant_user_id == user.id,
                models.RequestOffer.status.in_(("offered", "matched")),
            )
            .all()
        ):
            consultant_offer_meta[(co.request_kind, int(co.request_id))] = (
                int(co.id),
                (co.status or "").strip(),
            )
    consultant_offer_by_request = {k: v[0] for k, v in consultant_offer_meta.items()}

    def _mark_row_pending_inquiry_reply(row: dict[str, Any]) -> None:
        row["pending_inquiry_reply"] = False
        if not getattr(user, "is_consultant", False):
            return
        oid = row.get("offer_id")
        if oid is not None and int(oid) in pending_inquiry_offer_ids:
            row["pending_inquiry_reply"] = True
            return
        sk = row.get("sel_key") or ""
        key: tuple[str, int] | None = None
        if sk.startswith("rfp:"):
            try:
                key = ("rfp", int(sk.split(":", 1)[1]))
            except (ValueError, IndexError):
                key = None
        elif sk.startswith("ana:"):
            try:
                key = ("analysis", int(sk.split(":", 1)[1]))
            except (ValueError, IndexError):
                key = None
        elif sk.startswith("int:"):
            try:
                key = ("integration", int(sk.split(":", 1)[1]))
            except (ValueError, IndexError):
                key = None
        if not key:
            return
        oix = consultant_offer_by_request.get(key)
        if oix is not None and oix in pending_inquiry_offer_ids:
            row["pending_inquiry_reply"] = True

    for row in rows:
        _mark_row_pending_inquiry_reply(row)

    def _attach_console_offer_meta(row: dict[str, Any]) -> None:
        if row.get("offer_id") is not None:
            row["console_offer_id"] = int(row["offer_id"])
            row["console_offer_status"] = (row.get("offer_status") or "").strip()
            return
        lk = _console_sel_key_to_offer_lookup_key(row.get("sel_key") or "")
        if lk and lk in consultant_offer_meta:
            oid, st = consultant_offer_meta[lk]
            row["console_offer_id"] = oid
            row["console_offer_status"] = st
        else:
            row["console_offer_id"] = None
            row["console_offer_status"] = None

    for row in rows:
        _attach_console_offer_meta(row)

    console_offer_pending_inquiry = bool(getattr(user, "is_consultant", False) and pending_inquiry_offer_ids)

    selected_key = (request.query_params.get("sel") or "").strip()
    selected_row = next((r for r in rows if r["sel_key"] == selected_key), None) if selected_key else None
    if selected_row is None and rows:
        selected_row = rows[0]

    if selected_row:
        if getattr(user, "is_consultant", False):
            oid = selected_row.get("console_offer_id")
            st = (selected_row.get("console_offer_status") or "").strip()
            can_init = False
            if oid and st == "matched":
                cnt = (
                    db.query(models.RequestOfferInquiry)
                    .filter(models.RequestOfferInquiry.request_offer_id == int(oid))
                    .count()
                )
                can_init = cnt == 0
            selected_row["console_can_init_inquiry"] = can_init
        else:
            selected_row["console_can_init_inquiry"] = False

    bucket_meta = standard_menu_bucket_meta()
    kind_labels = {
        "all": "전체",
        "abap": "신규개발",
        "analysis": "분석개선",
        "integration": "연동개발",
        "offer": "오퍼",
        "matching": "매칭",
    }
    return templates.TemplateResponse(
        request,
        "request_console.html",
        {
            "request": request,
            "user": user,
            "kind": kind,
            "bucket": bucket,
            "rows": rows,
            "selected_row": selected_row,
            "counts_by_kind": counts_by_kind,
            "kind_labels": kind_labels,
            "bucket_meta": bucket_meta,
            "menu_search_title": title_search or "",
            "menu_date_from_raw": date_from_raw or "",
            "menu_date_to_raw": date_to_raw or "",
            "console_offer_pending_inquiry": console_offer_pending_inquiry,
            "console_consultant_inquiry_err": (
                request.query_params.get("console_consultant_inquiry_err") or ""
            ).strip(),
            "console_consultant_inquiry_ok": (request.query_params.get("console_consultant_inquiry_ok") or "").strip()
            == "1",
        },
    )


@router.post("/request-console/consultant-inquiry")
def request_console_consultant_inquiry_submit(
    request: Request,
    sel_key: str = Form(""),
    body: str = Form(""),
    return_kind: str = Form("all"),
    return_bucket: str = Form("all"),
    return_sel: str = Form(""),
    return_title: str = Form(""),
    return_date_from: str = Form(""),
    return_date_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/request-console", status_code=302)
    if not getattr(user, "is_consultant", False):
        return RedirectResponse(url="/", status_code=302)

    raw = (sel_key or "").strip().lower()
    if ":" not in raw:
        return RedirectResponse(url="/request-console", status_code=303)
    prefix, sid = raw.split(":", 1)
    try:
        req_id = int(sid)
    except Exception:
        return RedirectResponse(url="/request-console", status_code=303)

    if prefix == "rfp":
        req_kind = "rfp"
    elif prefix == "ana":
        req_kind = "analysis"
    elif prefix == "int":
        req_kind = "integration"
    else:
        return RedirectResponse(url="/request-console", status_code=303)

    offer = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.request_kind == req_kind,
            models.RequestOffer.request_id == req_id,
            models.RequestOffer.consultant_user_id == user.id,
            models.RequestOffer.status == "matched",
        )
        .first()
    )
    base = _request_console_return_location(
        return_kind=return_kind,
        return_bucket=return_bucket,
        return_sel=(return_sel or "").strip() or raw,
        return_title=return_title,
        return_date_from=return_date_from,
        return_date_to=return_date_to,
    )
    sep = "&" if "?" in base else "?"

    if not offer:
        return RedirectResponse(
            url=f"{base}{sep}console_consultant_inquiry_err={quote('매칭된 요청에서만 회원에게 먼저 문의할 수 있습니다.')}",
            status_code=303,
        )

    owner, title = _console_request_title_and_owner(db, req_kind, req_id)
    if not owner:
        return RedirectResponse(
            url=f"{base}{sep}console_consultant_inquiry_err={quote('요청을 찾을 수 없습니다.')}",
            status_code=303,
        )

    detail = _console_public_detail_url(request, req_kind, req_id)
    err, _row = send_consultant_matched_first_inquiry_to_owner(
        db,
        consultant=user,
        offer=offer,
        owner=owner,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    if err:
        return RedirectResponse(url=f"{base}{sep}console_consultant_inquiry_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}console_consultant_inquiry_ok=1", status_code=303)


@router.post("/request-console/offer")
def request_console_offer_submit(
    request: Request,
    sel_key: str = Form(""),
    return_kind: str = Form("all"),
    return_bucket: str = Form("all"),
    return_sel: str = Form(""),
    return_title: str = Form(""),
    return_date_from: str = Form(""),
    return_date_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/request-console", status_code=302)
    if not (user.is_admin or user.is_consultant):
        return RedirectResponse(url="/", status_code=302)

    raw = (sel_key or "").strip().lower()
    if ":" not in raw:
        return RedirectResponse(url="/request-console", status_code=303)
    prefix, sid = raw.split(":", 1)
    try:
        req_id = int(sid)
    except Exception:
        return RedirectResponse(url="/request-console", status_code=303)

    if prefix == "rfp":
        req_kind = "rfp"
    elif prefix == "ana":
        req_kind = "analysis"
    elif prefix == "int":
        req_kind = "integration"
    else:
        return RedirectResponse(url="/request-console", status_code=303)

    exists = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.request_kind == req_kind,
            models.RequestOffer.request_id == req_id,
            models.RequestOffer.consultant_user_id == user.id,
        )
        .first()
    )
    if not exists:
        db.add(
            models.RequestOffer(
                request_kind=req_kind,
                request_id=req_id,
                consultant_user_id=user.id,
                status="offered",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

    loc = _request_console_return_location(
        return_kind=return_kind,
        return_bucket=return_bucket,
        return_sel=(return_sel or "").strip() or raw,
        return_title=return_title,
        return_date_from=return_date_from,
        return_date_to=return_date_to,
    )
    return RedirectResponse(url=loc, status_code=303)


@router.get("/services/abap", response_class=HTMLResponse)
def services_abap_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    raw = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    intro_md = (raw.get("service_abap_intro_md_ko") or "").strip() or DEFAULT_SERVICE_ABAP_INTRO_MD_KO
    intro_html = _markdown_to_html(intro_md)

    qp = request.query_params
    bucket_raw = (qp.get("bucket") or "").strip() or None
    if bucket_raw and bucket_raw not in VALID_URL_BUCKETS:
        bucket_raw = None
    selected_bucket = bucket_raw

    title_search = (qp.get("title") or "").strip() or None
    date_from_raw = (qp.get("date_from") or "").strip() or None
    date_to_raw = (qp.get("date_to") or "").strip() or None
    date_from_dt = parse_slashed_date(date_from_raw)
    date_to_dt = parse_slashed_date(date_to_raw)

    rfp_total_rows = 0
    rfp_landing_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    svc_abap_tile_links: dict[str, str] = {}
    rfps_filtered: list = []

    show_rfp_owner = False
    proposal_offer_notice_count = 0
    if user:
        # 메뉴 첫 화면은 권한자도 본인 요청만 표시
        admin_view = False
        show_rfp_owner = False

        cnt, _buckets = rfp_landing_aggregate(db, admin=admin_view, user_id=user.id)
        rfp_landing_counts = cnt
        rfp_total_rows = sum(
            rfp_landing_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft")
        )
        presets = menu_landing_preset_params(request.query_params)
        svc_abap_tile_links = {
            k: menu_landing_url("/services/abap", presets, k) for k in TILE_ORDER_WITH_ALL
        }

        if selected_bucket:
            rfps_filtered = filtered_rfp_list_for_landing(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            offered_ids = _offered_request_id_set(
                db, "rfp", [int(x.id) for x in rfps_filtered], pending_only=True
            )
            for row in rfps_filtered:
                ho = int(row.id) in offered_ids
                setattr(row, "has_offer", ho)
                if selected_bucket == "proposal" and ho:
                    proposal_offer_notice_count += 1
                setattr(row, "pulse_offer_bg", selected_bucket == "proposal" and ho)

    bucket_meta = standard_menu_bucket_meta()
    proposal_offer_badges = (
        user_proposal_pending_offer_badges(db, user.id) if user else {"rfp": False, "analysis": False, "integration": False}
    )
    return templates.TemplateResponse(
        request,
        "services_abap.html",
        {
            "request": request,
            "user": user,
            "service_abap_intro_html": intro_html,
            "rfp_landing_counts": rfp_landing_counts,
            "rfp_total_rows": rfp_total_rows,
            "svc_abap_filtered_rfps": rfps_filtered if user else [],
            "svc_abap_tile_links": svc_abap_tile_links,
            "svc_abap_tile_order": list(TILE_ORDER_WITH_ALL),
            "selected_svc_abap_bucket": selected_bucket,
            "svc_abap_show_list": bool(user and selected_bucket),
            "svc_abap_search_title": title_search or "",
            "svc_abap_date_from_raw": date_from_raw or "",
            "svc_abap_date_to_raw": date_to_raw or "",
            "show_rfp_owner": show_rfp_owner,
            "bucket_meta": bucket_meta,
            "proposal_offer_badges": proposal_offer_badges,
            "proposal_offer_notice_count": proposal_offer_notice_count,
        },
    )


@router.get("/integration", response_class=HTMLResponse)
def integration_landing(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)

    raw_settings = {s.key: s.value for s in db.query(models.SiteSettings).all()}
    intro_md = (raw_settings.get("service_integration_intro_md_ko") or "").strip() or DEFAULT_SERVICE_INTEGRATION_INTRO_MD_KO
    service_integration_intro_html = _markdown_to_html(intro_md)

    qp = request.query_params
    bucket_raw = (qp.get("bucket") or "").strip() or None
    if bucket_raw and bucket_raw not in VALID_URL_BUCKETS:
        bucket_raw = None
    selected_bucket = bucket_raw

    title_search = (qp.get("title") or "").strip() or None
    date_from_raw = (qp.get("date_from") or "").strip() or None
    date_to_raw = (qp.get("date_to") or "").strip() or None
    date_from_dt = parse_slashed_date(date_from_raw)
    date_to_dt = parse_slashed_date(date_to_raw)

    menu_counts = {k: 0 for k in ("delivery", "proposal", "analysis", "in_progress", "draft")}
    menu_total_rows = 0
    menu_tile_links: dict[str, str] = {}
    filtered_rows: list[models.IntegrationRequest] = []
    show_request_owner = False
    proposal_offer_notice_count = 0

    if user:
        # 메뉴 첫 화면은 권한자도 본인 요청만 표시
        admin_view = False
        cnt, _b = integration_menu_aggregate(db, admin=admin_view, user_id=user.id)
        menu_counts = cnt
        menu_total_rows = sum(menu_counts[k] for k in ("delivery", "proposal", "analysis", "in_progress", "draft"))
        presets = menu_landing_preset_params(request.query_params)
        menu_tile_links = {k: menu_landing_url("/integration", presets, k) for k in TILE_ORDER_WITH_ALL}
        if selected_bucket:
            filtered_rows = filtered_integration_menu_rows(
                db,
                admin=admin_view,
                user_id=user.id,
                bucket=selected_bucket,
                title_q=title_search,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            offered_ids = _offered_request_id_set(
                db, "integration", [int(x.id) for x in filtered_rows], pending_only=True
            )
            for row in filtered_rows:
                ho = int(row.id) in offered_ids
                setattr(row, "has_offer", ho)
                if selected_bucket == "proposal" and ho:
                    proposal_offer_notice_count += 1
                setattr(row, "pulse_offer_bg", selected_bucket == "proposal" and ho)

    bucket_meta = standard_menu_bucket_meta()
    proposal_offer_badges = (
        user_proposal_pending_offer_badges(db, user.id) if user else {"rfp": False, "analysis": False, "integration": False}
    )
    return templates.TemplateResponse(
        request,
        "integration_landing.html",
        {
            "request": request,
            "user": user,
            "service_integration_intro_html": service_integration_intro_html,
            "bucket_meta": bucket_meta,
            "menu_landing_counts": menu_counts,
            "menu_total_rows": menu_total_rows,
            "menu_tile_links": menu_tile_links,
            "menu_tile_order": list(TILE_ORDER_WITH_ALL),
            "selected_menu_bucket": selected_bucket,
            "menu_show_list": bool(user and selected_bucket),
            "menu_search_title": title_search or "",
            "menu_date_from_raw": date_from_raw or "",
            "menu_date_to_raw": date_to_raw or "",
            "filtered_menu_rows": filtered_rows if user else [],
            "show_request_owner": show_request_owner,
            "menu_landing_form_action": "/integration",
            "proposal_offer_badges": proposal_offer_badges,
            "proposal_offer_notice_count": proposal_offer_notice_count,
            **_integration_impl_ui_ctx(db),
        },
    )


@router.get("/integration/new", response_class=HTMLResponse)
def integration_new_form(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/integration/new", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    return templates.TemplateResponse(
        request,
        "integration_form.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "devtypes": devtypes,
            "error": None,
            "form": None,
            "edit_ir": None,
            "integration_ref_code_initial": None,
            "attachment_entries": None,
            "ai_inquiry": {
                "mode": "teaser",
                "float_id": "integration-new-ai-teaser",
                "teaser_i18n": "chat.formAiTeaserInt",
            },
            **_integration_impl_ui_ctx(db),
        },
    )


@router.post("/integration/new")
async def integration_new_submit(
    request: Request,
    title: str = Form(""),
    impl_types: List[str] = Form(default=[]),
    sap_touchpoints: str = Form(""),
    environment_notes: str = Form(""),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    reference_code_json: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_dict():
        return {
            "title": title,
            "impl_types": impl_types,
            "sap_touchpoints": sap_touchpoints,
            "environment_notes": environment_notes,
            "description": description,
            "notes": notes_in,
        }

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "too_many_attachments",
                "form": _form_dict(),
            },
            status_code=400,
        )

    att_entries: list[dict] = []
    if n_uploads:
        att_entries, err_a = await _build_attachment_entries_from_uploads(
            user.id, attachments, notes_in
        )
        if err_a:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": err_a,
                    "form": _form_dict(),
                },
                status_code=400,
            )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "reference_code_too_large",
                "form": _form_dict(),
            },
            status_code=400,
        )

    allowed_impl = integration_impl_allowed_codes(db)
    impl_clean = [x for x in impl_types if x in allowed_impl]
    if not is_draft_save and not impl_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_impl_types",
                "form": _form_dict(),
            },
            status_code=400,
        )
    title_clean = (title or "").strip()
    if not is_draft_save and not title_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_title",
                "form": _form_dict(),
            },
            status_code=400,
        )
    display_title = title_clean or "SAP 연동 개발 요청 (임시)"
    ir = models.IntegrationRequest(
        user_id=user.id,
        title=display_title,
        impl_types=",".join(impl_clean) if impl_clean else "",
        sap_touchpoints=sap_touchpoints.strip() or None,
        environment_notes=environment_notes.strip() or None,
        security_notes=None,
        description=description.strip() or None,
        reference_code_payload=norm_ref,
        status="draft" if is_draft_save else "submitted",
        interview_status="pending",
    )
    _set_attachments(ir, att_entries)
    db.add(ir)
    db.commit()
    db.refresh(ir)
    if is_draft_save:
        return RedirectResponse(url=f"/integration/{ir.id}/edit", status_code=302)
    return RedirectResponse(url=f"/integration/{ir.id}", status_code=302)


@router.post("/integration/{req_id}/duplicate-request")
def integration_duplicate_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """본인 연동 요청을 초안으로 복사한 뒤 수정 폼으로 이동합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    entries = duplicate_attachment_entries(_attachment_entries(ir), user_id=user.id)
    title = (ir.title or "").strip()
    if title and not title.endswith(" (복사)"):
        title = f"{title} (복사)"
    new_ir = models.IntegrationRequest(
        user_id=user.id,
        title=title or "복사된 연동 요청",
        impl_types=ir.impl_types,
        sap_touchpoints=ir.sap_touchpoints,
        environment_notes=ir.environment_notes,
        security_notes=ir.security_notes,
        description=ir.description,
        reference_code_payload=ir.reference_code_payload,
        status="draft",
        interview_status="pending",
        workflow_rfp_id=None,
        improvement_request_text=None,
    )
    _set_attachments(new_ir, entries)
    db.add(new_ir)
    db.commit()
    db.refresh(new_ir)
    return RedirectResponse(url=f"/integration/{new_ir.id}/edit", status_code=302)


@router.post("/integration/{req_id}/delete")
def integration_delete(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id)
    if not user.is_admin:
        q = q.filter(models.IntegrationRequest.user_id == user.id)
    ir = q.first()
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    fs_s = (getattr(ir, "fs_status", None) or "none").strip().lower() or "none"
    if fs_s == "ready" and (getattr(ir, "fs_text", None) or "").strip():
        return RedirectResponse(url=f"/integration/{req_id}?delete_blocked=fs", status_code=302)
    for ent in _attachment_entries(ir):
        _remove_stored_file(ent.get("path"))
    db.delete(ir)
    db.commit()
    return RedirectResponse(url="/integration", status_code=302)


@router.get("/integration/{req_id}/edit", response_class=HTMLResponse)
def integration_edit_form(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(
            url=f"/login?next={quote('/integration/' + str(req_id) + '/edit')}",
            status_code=302,
        )
    ir = (
        db.query(models.IntegrationRequest)
        .options(joinedload(models.IntegrationRequest.followup_messages))
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir or (ir.status or "").strip().lower() != "draft":
        return RedirectResponse(url="/integration", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    ents = _attachment_entries(ir)
    notes: list[str] = []
    for i in range(5):
        notes.append((ents[i].get("note") or "") if i < len(ents) else "")
    raw_impl = [t.strip() for t in (ir.impl_types or "").split(",") if t.strip()]
    form = {
        "title": ir.title or "",
        "impl_types": raw_impl,
        "sap_touchpoints": ir.sap_touchpoints or "",
        "environment_notes": ir.environment_notes or "",
        "description": ir.description or "",
        "notes": notes,
    }
    ref_init = None
    if ir.reference_code_payload:
        try:
            ref_init = json.loads(ir.reference_code_payload)
        except Exception:
            ref_init = None
    follow_msgs = sorted(
        list(ir.followup_messages or []),
        key=lambda m: (m.created_at or ir.created_at),
    )
    followup_turns = _pair_integration_followup_turns(follow_msgs)
    n_fu = sum(1 for m in follow_msgs if (m.role or "") == "user")
    chat_err = (request.query_params.get("chat_err") or "").strip() or None
    ai_inquiry = {
        "mode": "live",
        "float_id": "integration-followup-chat",
        "size_key": "integration-followup-chat-size",
        "post_url": f"/integration/{ir.id}/chat",
        "return_to": "edit",
        "followup_turns": followup_turns,
        "chat_error": chat_err,
        "chat_limit_reached": n_fu >= INT_CHAT_MAX_USER,
        "max_turns": INT_CHAT_MAX_USER,
        "header_i18n": "chat.intHeaderTitle",
        "context_i18n": "chat.intContextHelp",
        "form_ready": True,
    }
    return templates.TemplateResponse(
        request,
        "integration_form.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "devtypes": devtypes,
            **_integration_impl_ui_ctx(db),
            "error": None,
            "form": form,
            "edit_ir": ir,
            "integration_ref_code_initial": ref_init,
            "attachment_entries": ents,
            "ai_inquiry": ai_inquiry,
        },
    )


@router.post("/integration/{req_id}/edit")
async def integration_edit_submit(
    req_id: int,
    request: Request,
    title: str = Form(""),
    impl_types: List[str] = Form(default=[]),
    sap_touchpoints: str = Form(""),
    environment_notes: str = Form(""),
    description: str = Form(""),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    reference_code_json: str = Form(""),
    save_action: str = Form("submit"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir or (ir.status or "").strip().lower() != "draft":
        return RedirectResponse(url="/integration", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    is_draft_save = (save_action or "").strip().lower() == "draft"

    def _form_dict():
        return {
            "title": title,
            "impl_types": impl_types,
            "sap_touchpoints": sap_touchpoints,
            "environment_notes": environment_notes,
            "description": description,
            "notes": notes_in,
        }

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "too_many_attachments",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": _attachment_entries(ir),
            },
            status_code=400,
        )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        ref_init = None
        if (reference_code_json or "").strip():
            try:
                ref_init = json.loads(reference_code_json)
            except Exception:
                ref_init = None
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "reference_code_too_large",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": ref_init,
                "attachment_entries": _attachment_entries(ir),
            },
            status_code=400,
        )

    merged_att = list(_attachment_entries(ir))
    if n_uploads:
        new_e, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": err_a,
                    "form": _form_dict(),
                    "edit_ir": ir,
                    "integration_ref_code_initial": None,
                    "attachment_entries": merged_att,
                },
                status_code=400,
            )
        merged_att = merged_att + (new_e or [])
        if len(merged_att) > MAX_RFP_ATTACHMENTS:
            return templates.TemplateResponse(
                request,
                "integration_form.html",
                {
                    "request": request,
                    "user": user,
                    "modules": modules,
                    "devtypes": devtypes,
                    **_integration_impl_ui_ctx(db),
                    "error": "too_many_attachments",
                    "form": _form_dict(),
                    "edit_ir": ir,
                    "integration_ref_code_initial": None,
                    "attachment_entries": merged_att,
                },
                status_code=400,
            )

    allowed_impl = integration_impl_allowed_codes(db)
    impl_clean = [x for x in impl_types if x in allowed_impl]
    if not is_draft_save and not impl_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_impl_types",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": merged_att,
            },
            status_code=400,
        )
    title_clean = (title or "").strip()
    if not is_draft_save and not title_clean:
        return templates.TemplateResponse(
            request,
            "integration_form.html",
            {
                "request": request,
                "user": user,
                "modules": modules,
                "devtypes": devtypes,
                **_integration_impl_ui_ctx(db),
                "error": "need_title",
                "form": _form_dict(),
                "edit_ir": ir,
                "integration_ref_code_initial": None,
                "attachment_entries": merged_att,
            },
            status_code=400,
        )

    ir.title = title_clean or ir.title or "SAP 연동 개발 요청 (임시)"
    ir.impl_types = ",".join(impl_clean) if impl_clean else ""
    ir.sap_touchpoints = sap_touchpoints.strip() or None
    ir.environment_notes = environment_notes.strip() or None
    ir.security_notes = None
    ir.description = description.strip() or None
    ir.reference_code_payload = norm_ref
    if is_draft_save:
        ir.status = "draft"
    else:
        ir.status = "submitted"
        ir.interview_status = "pending"
    _set_attachments(ir, merged_att)
    db.add(ir)
    db.commit()
    if is_draft_save:
        return RedirectResponse(url=f"/integration/{ir.id}/edit", status_code=302)
    return RedirectResponse(url=f"/integration/{ir.id}", status_code=302)


def _collect_integration_unified_hub_ctx(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    *,
    phase: str | None,
    view: str | None,
    db: Session,
    readonly_console: bool,
) -> RedirectResponse | dict[str, Any]:
    """연동 개발 통합 상세와 요청 Console 조회 전용 뷰의 공통 컨텍스트."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    requested_phase = normalize_integration_hub_phase(phase)
    view_summary = (view or "").strip().lower() == "summary" and requested_phase == "interview"

    q = apply_integration_hub_read_access(
        db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id),
        user,
        console_embed=bool(readonly_console),
    )
    ir = (
        q.options(
            joinedload(models.IntegrationRequest.followup_messages),
            joinedload(models.IntegrationRequest.workflow_rfp),
            joinedload(models.IntegrationRequest.interview_messages),
        ).first()
    )
    if not ir:
        return RedirectResponse(url="/", status_code=302)

    st = (ir.status or "").strip().lower()
    if readonly_console and st == "draft":
        requested_phase = normalize_integration_hub_phase("request")

    if (not readonly_console) and st == "draft" and requested_phase != "request":
        return RedirectResponse(url=f"/integration/{req_id}/edit", status_code=302)

    display_phase = requested_phase
    hub_embedded = False
    hub_proposal_generating_override = False
    ws_out = None

    if (not readonly_console) and requested_phase == "interview" and not view_summary:
        ws_out = serve_integration_interview_workspace(request, db, user, ir, background_tasks)
        db.refresh(ir)
        if ws_out.kind == "redirect":
            return RedirectResponse(url=ws_out.redirect_url or "/", status_code=302)
        if ws_out.kind == "generating":
            display_phase = "proposal"
            hub_proposal_generating_override = True
        elif ws_out.kind == "wizard" and ws_out.wizard_ctx:
            hub_embedded = True
            display_phase = "interview"
            ws_out.wizard_ctx["iv_submit_base"] = f"/integration/{req_id}"

    types_list = [t for t in (ir.impl_types or "").split(",") if t.strip()]
    program_groups = reference_code_program_groups_for_tabs(ir.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in program_groups)
    owner = None
    if getattr(user, "is_admin", False) or (
        readonly_console and getattr(user, "is_consultant", False)
    ) or consultant_has_request_offer(
        db, consultant_user_id=user.id, request_kind="integration", request_id=ir.id
    ):
        owner = db.query(models.User).filter(models.User.id == ir.user_id).first()

    imsgs = sorted(list(ir.interview_messages or []), key=lambda m: (m.round_number, m.id))
    answered_sorted = [m for m in imsgs if m.is_answered]
    interview_summary_messages = _messages_to_list(answered_sorted)
    proposal_round_messages = interview_summary_messages

    hub_proposal_generating = hub_proposal_generating_override or (
        (ir.interview_status or "") == "generating_proposal"
    )

    proposal_html = ""
    if (ir.interview_status or "") == "completed" and (ir.proposal_text or "").strip():
        proposal_html = _markdown_to_html(wrap_unbracketed_agent_names(ir.proposal_text or ""))

    fs_stat = (getattr(ir, "fs_status", None) or "none").strip() or "none"
    dc_stat = (getattr(ir, "delivered_code_status", None) or "none").strip() or "none"
    fs_html = ""
    if fs_stat == "ready" and (getattr(ir, "fs_text", None) or "").strip():
        fs_html = _markdown_to_html(ir.fs_text)
    delivered_code_html = ""
    if dc_stat == "ready" and (getattr(ir, "delivered_code_text", None) or "").strip():
        delivered_code_html = _markdown_to_html(ir.delivered_code_text)

    fs_busy = fs_stat == "generating"
    dc_busy = dc_stat == "generating"
    gen_busy = fs_busy or dc_busy

    fs_body = (getattr(ir, "fs_text", None) or "").strip()
    can_operate_delivery_flag = user_can_operate_delivery(user)
    can_start_delivered_code = (
        False
        if readonly_console
        else (bool(can_operate_delivery_flag) and bool(fs_body) and (dc_stat != "generating"))
    )

    if readonly_console:
        followup_turns = []
        chat_limit_reached = False
        chat_error = None
        hub_scripts = False
    else:
        follow_msgs = sorted(
            list(ir.followup_messages or []),
            key=lambda m: (m.created_at or ir.created_at),
        )
        followup_turns = _pair_integration_followup_turns(follow_msgs)
        n_followup_user = sum(1 for m in follow_msgs if (m.role or "") == "user")
        chat_limit_reached = n_followup_user >= INT_CHAT_MAX_USER
        chat_error = (request.query_params.get("chat_err") or "").strip() or None
        hub_scripts = bool(proposal_html) and not hub_proposal_generating

    delete_blocked = (request.query_params.get("delete_blocked") or "").strip()

    vis_int_offers = visible_request_offers_for_viewer(
        _integration_offer_rows(db, ir.id),
        viewer=user,
        owner_user_id=ir.user_id,
        privileged_operator=bool(getattr(user, "is_admin", False)),
    )

    code_asset_unlocked = user_may_copy_download_request_assets(
        db,
        user,
        request_kind="integration",
        request_id=req_id,
        owner_user_id=int(ir.user_id),
    )

    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "ir": ir,
        "rfp": ir,
        "code_asset_unlocked": code_asset_unlocked,
        "iv_submit_base": f"/integration/{req_id}",
        "owner": owner,
        "delete_blocked_reason": delete_blocked,
        "hub_phase_open": display_phase,
        "hub_embedded": hub_embedded,
        "attachment_entries": _attachment_entries(ir),
        **_integration_impl_ui_ctx(db),
        "types_list": types_list,
        "source_program_groups": program_groups,
        "reference_section_count": ref_section_count,
        "interview_summary_messages": interview_summary_messages,
        "proposal_round_messages": proposal_round_messages,
        "hub_proposal_generating": hub_proposal_generating,
        "proposal_html": proposal_html,
        "fs_html": fs_html,
        "delivered_code_html": delivered_code_html,
        "fs_stat": fs_stat,
        "dc_stat": dc_stat,
        "fs_busy": fs_busy,
        "dc_busy": dc_busy,
        "gen_busy": gen_busy,
        "can_start_delivered_code": can_start_delivered_code,
        "can_operate_delivery": can_operate_delivery_flag,
        "followup_turns": followup_turns,
        "chat_limit_reached": chat_limit_reached,
        "chat_error": chat_error,
        "max_followup_user_turns": INT_CHAT_MAX_USER,
        "hub_include_proposal_scripts": hub_scripts,
        "request_offers": vis_int_offers,
        "request_offer_can_match": bool(user and ir and user.id == ir.user_id and not readonly_console),
        "request_offer_profile_url_builder": lambda offer_id: f"/integration/{ir.id}/offers/{int(offer_id)}/profile",
        "request_offer_match_url_builder": lambda offer_id: f"/integration/{ir.id}/offers/{int(offer_id)}/match",
        "request_offer_inquiries_by_offer_id": inquiries_by_offer_id(db, [int(o.id) for o in vis_int_offers]),
        "request_offer_inquiry_url_builder": lambda offer_id: f"/integration/{ir.id}/offers/{int(offer_id)}/inquiry",
        "request_offer_can_inquire": bool(user and ir and user.id == ir.user_id and not readonly_console),
        "offer_inquiry_request_detail_url": public_request_url(
            request, f"/integration/{ir.id}?phase=proposal"
        ),
        "offer_inquiry_err": (request.query_params.get("offer_inquiry_err") or "").strip(),
        "offer_inquiry_ok": (request.query_params.get("offer_inquiry_ok") or "").strip() == "1",
        "offer_inquiry_reply_err": (request.query_params.get("offer_inquiry_reply_err") or "").strip(),
        "offer_inquiry_reply_ok": (request.query_params.get("offer_inquiry_reply_ok") or "").strip() == "1",
        "request_offer_inquiry_reply_url_builder": lambda offer_id: f"/integration/{ir.id}/offers/{int(offer_id)}/inquiry-reply",
    }

    if hub_embedded and ws_out is not None and ws_out.kind == "wizard" and ws_out.wizard_ctx:
        ctx.update(ws_out.wizard_ctx)

    if (not readonly_console) and hub_proposal_generating:
        ctx["rfp"] = SimpleNamespace(id=ir.id, title=ir.title or "")
        ctx["proposal_status_url"] = f"/integration/{ir.id}/proposal/status"
        ctx["proposal_done_redirect_url"] = integration_hub_url(ir.id, "proposal")

    return ctx


@router.get("/integration/{req_id}/generation-status")
def integration_generation_status(req_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    q = apply_integration_hub_read_access(
        db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id),
        user,
    )
    ir = q.first()
    if not ir:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse(
        {
            "fs_status": getattr(ir, "fs_status", None) or "none",
            "delivered_code_status": getattr(ir, "delivered_code_status", None) or "none",
            "fs_job_log": getattr(ir, "fs_job_log", None) or "",
            "delivered_job_log": getattr(ir, "delivered_job_log", None) or "",
            "fs_error": getattr(ir, "fs_error", None) or "",
            "delivered_code_error": getattr(ir, "delivered_code_error", None) or "",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/integration/{req_id}/console-readonly", response_class=HTMLResponse)
def integration_detail_console_readonly(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    phase: str | None = None,
    view: str | None = None,
    db: Session = Depends(get_db),
):
    out = _collect_integration_unified_hub_ctx(
        req_id,
        request,
        background_tasks,
        phase=phase,
        view=view,
        db=db,
        readonly_console=True,
    )
    if isinstance(out, RedirectResponse):
        return out
    out["layout_template"] = layout_template_from_embed_query(request)
    return templates.TemplateResponse(request, "integration_unified_hub_readonly.html", out)


@router.get("/integration/{req_id}", response_class=HTMLResponse)
def integration_detail(
    req_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    phase: str | None = None,
    view: str | None = None,
    db: Session = Depends(get_db),
):
    """연동 개발 통합 상세 — 요청·인터뷰·제안서·FS·구현 가이드."""
    ctx = _collect_integration_unified_hub_ctx(
        req_id,
        request,
        background_tasks,
        phase=phase,
        view=view,
        db=db,
        readonly_console=False,
    )
    if isinstance(ctx, RedirectResponse):
        return ctx
    return templates.TemplateResponse(request, "integration_unified_hub.html", ctx)


@router.post("/integration/{req_id}/chat")
def integration_chat_post(
    req_id: int,
    request: Request,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    from urllib.parse import quote

    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(
            models.IntegrationRequest.id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)

    st = (ir.status or "").strip().lower()
    chat_base = (
        f"/integration/{req_id}/edit"
        if st == "draft"
        else f"/integration/{req_id}?phase=request"
    )

    msg, verr = validate_integration_user_message(message)
    if verr:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote(verr)}#integration-followup-chat",
            status_code=303,
        )

    n_user = (
        db.query(models.IntegrationFollowupMessage)
        .filter(
            models.IntegrationFollowupMessage.request_id == ir.id,
            models.IntegrationFollowupMessage.role == "user",
        )
        .count()
    )
    if n_user >= INT_CHAT_MAX_USER:
        return RedirectResponse(
            url=f"{chat_base}?chat_err={quote('후속 질문은 상한에 도달했습니다.')}#integration-followup-chat",
            status_code=303,
        )

    prior = (
        db.query(models.IntegrationFollowupMessage)
        .filter(models.IntegrationFollowupMessage.request_id == ir.id)
        .order_by(models.IntegrationFollowupMessage.created_at.asc())
        .all()
    )

    try:
        att_digest = build_attachment_llm_digest(_attachment_entries(ir), max_total_chars=10_000)
        reply = generate_integration_followup_reply(
            ir_summary=integration_request_llm_summary(ir, db),
            history_messages=prior,
            user_question=msg,
            attachment_digest=att_digest,
        )
    except Exception:
        reply = "응답을 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    db.add(
        models.IntegrationFollowupMessage(
            request_id=ir.id,
            role="user",
            content=msg,
        )
    )
    db.add(
        models.IntegrationFollowupMessage(
            request_id=ir.id,
            role="assistant",
            content=reply,
        )
    )
    db.commit()
    return RedirectResponse(url=f"{chat_base}#integration-followup-chat", status_code=303)


@router.post("/integration/{req_id}/offers/{offer_id}/match")
def integration_offer_match(
    req_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "integration",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=f"/integration/{req_id}?phase=proposal", status_code=303)
    if (offer.status or "") == "matched":
        offer.status = "offered"
        offer.matched_at = None
        db.add(offer)
        db.commit()
        return RedirectResponse(url=f"/integration/{req_id}?phase=proposal", status_code=303)
    db.query(models.RequestOffer).filter(
        models.RequestOffer.request_kind == "integration",
        models.RequestOffer.request_id == req_id,
    ).update({"status": "offered", "matched_at": None}, synchronize_session=False)
    offer.status = "matched"
    offer.matched_at = datetime.utcnow()
    db.add(offer)
    db.commit()
    return RedirectResponse(url=f"/integration/{req_id}?phase=proposal", status_code=303)


@router.post("/integration/{req_id}/offers/{offer_id}/inquiry")
def integration_offer_inquiry_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "integration",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=303)
    title = (ir.title or "").strip() or f"연동 #{req_id}"
    detail = public_request_url(request, f"/integration/{req_id}?phase=proposal")
    err, _row = send_offer_inquiry_from_owner(
        db,
        author=user,
        offer=offer,
        consultant=offer.consultant,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = integration_hub_url(req_id, "proposal")
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_ok=1", status_code=303)


@router.post("/integration/{req_id}/offers/{offer_id}/inquiry-reply")
def integration_offer_inquiry_reply_post(
    req_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not getattr(user, "is_consultant", False):
        return RedirectResponse(url="/", status_code=302)
    ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id).first()
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "integration",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=303)
    owner = db.query(models.User).filter(models.User.id == ir.user_id).first()
    if not owner:
        return RedirectResponse(url=integration_hub_url(req_id, "proposal"), status_code=303)
    title = (ir.title or "").strip() or f"연동 #{req_id}"
    detail = public_request_url(request, f"/integration/{req_id}?phase=proposal")
    err, _row = send_consultant_offer_inquiry_reply(
        db,
        consultant=user,
        offer=offer,
        owner=owner,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = integration_hub_url(req_id, "proposal")
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_ok=1", status_code=303)


@router.get("/integration/{req_id}/offers/{offer_id}/profile")
def integration_offer_profile_download(
    req_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(models.IntegrationRequest.id == req_id, models.IntegrationRequest.user_id == user.id)
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "integration",
            models.RequestOffer.request_id == req_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=f"/integration/{req_id}?phase=request", status_code=302)
    path = (getattr(offer.consultant, "consultant_profile_file_path", None) or "").strip()
    fname = (getattr(offer.consultant, "consultant_profile_file_name", None) or "consultant_profile").strip() or "consultant_profile"
    if not path:
        return RedirectResponse(url=f"/integration/{req_id}?phase=request", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=f"/integration/{req_id}?phase=request", status_code=302)
        return RedirectResponse(url=r2_storage.presigned_get_url(ref, fname), status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url=f"/integration/{req_id}?phase=request", status_code=302)
    return FileResponse(ref, filename=fname)


@router.post("/integration/{req_id}/improvement-proposal")
def integration_improvement_proposal_post(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """레거시 폼 호환: 이제 이 화면의 2. 인터뷰 이후 단계에서 제안서를 생성합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ir = (
        db.query(models.IntegrationRequest)
        .filter(
            models.IntegrationRequest.id == req_id,
            models.IntegrationRequest.user_id == user.id,
        )
        .first()
    )
    if not ir:
        return RedirectResponse(url="/integration", status_code=302)
    return RedirectResponse(url=integration_hub_url(req_id, "interview"), status_code=302)


@router.get("/integration/{req_id}/attachment")
def integration_download_attachment(
    req_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = apply_integration_hub_read_access(
        db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == req_id),
        user,
    )
    ir = q.first()
    if not ir:
        return RedirectResponse(url="/", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="integration",
        request_id=req_id,
        owner_user_id=int(ir.user_id),
    ):
        return RedirectResponse(url="/", status_code=302)
    entries = _attachment_entries(ir)
    if idx < 0 or idx >= len(entries):
        return RedirectResponse(url="/", status_code=302)
    ent = entries[idx]
    path = ent.get("path")
    fname = ent.get("filename") or "attachment"
    if not path:
        return RedirectResponse(url="/", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url="/", status_code=302)
        url = r2_storage.presigned_get_url(ref, fname)
        return RedirectResponse(url=url, status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(ref, filename=fname)


@router.patch("/integration/{req_id}/reference-codes")
async def patch_integration_reference_codes(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    ir = db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.id == req_id,
        models.IntegrationRequest.user_id == user.id,
    ).first()
    if not ir:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    try:
        body = await request.json()
        raw = json.dumps(body, ensure_ascii=False)
        norm = normalize_reference_code_payload(raw)
    except ValueError:
        return JSONResponse({"ok": False, "error": "too_large"}, status_code=400)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    ir.reference_code_payload = norm
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/integration/{req_id}/reference-codes")
def delete_integration_reference_codes(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    ir = db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.id == req_id,
        models.IntegrationRequest.user_id == user.id,
    ).first()
    if not ir:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    ir.reference_code_payload = None
    db.commit()
    return JSONResponse({"ok": True})
