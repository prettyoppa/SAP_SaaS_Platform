"""요청자 §6 확인 필요 사항 — 추가 인터뷰."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..ai_usage_recorder import AiUsageContext, ai_usage_scope
from ..database import get_db
from ..delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP
from ..interview_answer_payload import parse_answer_payload_form
from ..proposal_section6_decisions import (
    get_entity_decisions_raw,
    load_request_entity_for_decisions,
    parse_section6_open_items,
    set_entity_decisions_raw,
)
from ..proposal_section6_interview import (
    advance_section6_interview,
    load_section6_payload,
    save_section6_payload,
    start_section6_interview,
)

router = APIRouter(tags=["proposal-decisions"])

SECTION6_INTERVIEW_ANCHOR = "proposal-section6-interview"


def _redirect(return_to: str | None, *, focus_section6: bool = False, **qp: str) -> str:
    raw = (return_to or "").strip() or "/"
    parts = urlsplit(raw)
    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    for k, v in qp.items():
        if not v:
            continue
        query_items = [(k2, v2) for k2, v2 in query_items if k2 != k]
        query_items.append((k, v))
    new_query = urlencode(query_items)
    fragment = SECTION6_INTERVIEW_ANCHOR if focus_section6 else parts.fragment
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, fragment))


def _owner_entity(
    db: Session, request_kind: str, request_id: int, actor_id: int
) -> tuple[models.RFP | models.IntegrationRequest | models.AbapAnalysisRequest | None, str]:
    entity = load_request_entity_for_decisions(db, request_kind, request_id)
    if not entity:
        return None, ""
    if int(getattr(entity, "user_id", 0) or 0) != int(actor_id):
        return None, ""
    title = (getattr(entity, "title", None) or "").strip()
    return entity, title


def _save_payload(db: Session, entity, payload: dict) -> None:
    set_entity_decisions_raw(entity, save_section6_payload(payload))
    db.add(entity)
    db.commit()


@router.post("/rfp/{rfp_id}/proposal-section6-interview/start")
def rfp_section6_interview_start(
    rfp_id: int,
    request: Request,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_RFP, int(rfp_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    open_items = parse_section6_open_items(entity.proposal_text or "")
    with ai_usage_scope(
        AiUsageContext(user_id=int(user.id), request_kind="rfp", request_id=int(rfp_id))
    ):
        payload = start_section6_interview(open_items=open_items, request_title=title)
    _save_payload(db, entity, payload)
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )


@router.post("/rfp/{rfp_id}/proposal-section6-interview/answer")
async def rfp_section6_interview_answer(
    rfp_id: int,
    request: Request,
    return_to: str = Form(""),
    current_answer: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_RFP, int(rfp_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    form = await request.form()
    answer_payload = (form.get("answer_payload") or "").strip()
    payload = load_section6_payload(get_entity_decisions_raw(entity))
    try:
        with ai_usage_scope(
            AiUsageContext(user_id=int(user.id), request_kind="rfp", request_id=int(rfp_id))
        ):
            o = parse_answer_payload_form(answer_payload, current_answer)
            payload = advance_section6_interview(
                payload,
                answer_payload=o,
                current_answer=current_answer,
                request_title=title,
            )
    except ValueError:
        return RedirectResponse(
            url=_redirect(return_to, section6_decisions_err="answer_invalid"),
            status_code=303,
        )
    _save_payload(db, entity, payload)
    inv = payload.get("interview") or {}
    if (inv.get("status") or "").strip() == "complete":
        return RedirectResponse(
            url=_redirect(return_to, focus_section6=True, section6_decisions="ok"),
            status_code=303,
        )
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )


@router.post("/integration/{req_id}/proposal-section6-interview/start")
def integration_section6_interview_start(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_INTEGRATION, int(req_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    open_items = parse_section6_open_items(entity.proposal_text or "")
    with ai_usage_scope(
        AiUsageContext(user_id=int(user.id), request_kind="integration", request_id=int(req_id))
    ):
        payload = start_section6_interview(open_items=open_items, request_title=title)
    _save_payload(db, entity, payload)
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )


@router.post("/integration/{req_id}/proposal-section6-interview/answer")
async def integration_section6_interview_answer(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    current_answer: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_INTEGRATION, int(req_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    form = await request.form()
    answer_payload = (form.get("answer_payload") or "").strip()
    payload = load_section6_payload(get_entity_decisions_raw(entity))
    try:
        with ai_usage_scope(
            AiUsageContext(
                user_id=int(user.id), request_kind="integration", request_id=int(req_id)
            )
        ):
            o = parse_answer_payload_form(answer_payload, current_answer)
            payload = advance_section6_interview(
                payload,
                answer_payload=o,
                current_answer=current_answer,
                request_title=title,
            )
    except ValueError:
        return RedirectResponse(
            url=_redirect(return_to, section6_decisions_err="answer_invalid"),
            status_code=303,
        )
    _save_payload(db, entity, payload)
    inv = payload.get("interview") or {}
    if (inv.get("status") or "").strip() == "complete":
        return RedirectResponse(
            url=_redirect(return_to, focus_section6=True, section6_decisions="ok"),
            status_code=303,
        )
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )


@router.post("/abap-analysis/{req_id}/proposal-section6-interview/start")
def abap_section6_interview_start(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_ANALYSIS, int(req_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    open_items = parse_section6_open_items(entity.proposal_text or "")
    with ai_usage_scope(
        AiUsageContext(user_id=int(user.id), request_kind="analysis", request_id=int(req_id))
    ):
        payload = start_section6_interview(open_items=open_items, request_title=title)
    _save_payload(db, entity, payload)
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )


@router.post("/abap-analysis/{req_id}/proposal-section6-interview/answer")
async def abap_section6_interview_answer(
    req_id: int,
    request: Request,
    return_to: str = Form(""),
    current_answer: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    entity, title = _owner_entity(db, KIND_ANALYSIS, int(req_id), int(user.id))
    if not entity:
        return RedirectResponse(url=_redirect(return_to, section6_decisions_err="forbidden"), status_code=303)
    form = await request.form()
    answer_payload = (form.get("answer_payload") or "").strip()
    payload = load_section6_payload(get_entity_decisions_raw(entity))
    try:
        with ai_usage_scope(
            AiUsageContext(user_id=int(user.id), request_kind="analysis", request_id=int(req_id))
        ):
            o = parse_answer_payload_form(answer_payload, current_answer)
            payload = advance_section6_interview(
                payload,
                answer_payload=o,
                current_answer=current_answer,
                request_title=title,
            )
    except ValueError:
        return RedirectResponse(
            url=_redirect(return_to, section6_decisions_err="answer_invalid"),
            status_code=303,
        )
    _save_payload(db, entity, payload)
    inv = payload.get("interview") or {}
    if (inv.get("status") or "").strip() == "complete":
        return RedirectResponse(
            url=_redirect(return_to, focus_section6=True, section6_decisions="ok"),
            status_code=303,
        )
    return RedirectResponse(
        url=_redirect(return_to, focus_section6=True, section6_interview="started"),
        status_code=303,
    )
