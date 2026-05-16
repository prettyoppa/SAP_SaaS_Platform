import io
import json
import mimetypes
import os
import zipfile
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from urllib.parse import quote, urlencode
from starlette.concurrency import run_in_threadpool
from typing import List, Optional, Tuple, Any

from .. import models, auth, r2_storage, sap_fields
from ..agent_display import wrap_unbracketed_agent_names
from ..followup_thread_scope import filter_followup_messages_for_viewer
from ..followup_messages_util import followup_created_at_sort_key
from ..delivered_code_package import (
    delivered_package_has_body,
    parse_delivered_code_payload,
    rfp_delivered_body_ready,
)
from ..offer_inquiry_service import (
    inquiries_by_offer_id,
    notify_consultant_request_matched,
    public_request_url,
    sanitize_console_readonly_return_url,
    send_consultant_offer_inquiry_reply,
    send_offer_inquiry_from_owner,
)
from ..paid_generation import resolved_fs_markdown_for_codegen
from ..code_asset_access import user_may_copy_download_request_assets
from ..request_hub_access import consultant_has_request_offer, consultant_is_matched_on_request
from ..request_offer_visibility import visible_request_offers_for_viewer
from ..paid_tier import (
    paid_engagement_is_active,
    rfp_eligible_for_stripe_checkout,
    user_can_access_fs_hub,
    user_can_operate_delivery,
)
from ..rfp_download_names import (
    content_disposition_attachment,
    delivered_abap_download_basename,
    delivered_code_zip_basename,
    fs_md_download_basename,
)
from ..rfp_form_suggest import (
    MIN_RFP_DESCRIPTION_CHARS,
    description_sufficient_for_suggest,
    suggest_program_id_from_title,
    suggest_title_from_description,
)
from ..rfp_reference_code import normalize_reference_code_payload, reference_code_program_groups_for_tabs
from ..rfp_hub import normalize_rfp_hub_phase, rfp_hub_url
from ..requirement_body import (
    apply_body as apply_requirement_body,
    display_ctx as requirement_display_ctx,
    duplicate_screenshots as duplicate_requirement_screenshots,
    inline_image_response,
    resolve_inline_entry,
    screenshot_entries as requirement_screenshot_entries,
    set_screenshot_entries,
)
from ..requirement_rich_text import html_to_plain_text, is_html_format
from ..workflow_abap_rfp_context import load_workflow_abap_mirror_context
from ..rfp_followup_chat import (
    generate_rfp_followup_reply,
    pair_followup_turn_messages,
    rfp_followup_context_block,
    validate_rfp_user_message,
)
from ..subscription_catalog import METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE
from ..subscription_quota import (
    ai_inquiry_limit_reached,
    ai_inquiry_snapshot,
    get_ai_inquiry_used,
    record_ai_inquiry_user_turn,
    try_consume_monthly,
)
from ..rfp_phase_gates import rfp_for_hub_readonly_embed, rfp_for_owner_or_admin, rfp_owned_only
from ..stripe_service import stripe_keys_configured
from . import interview_router as _interview_views
from ..database import get_db
from ..templates_config import layout_template_from_embed_query, templates
from ..writing_guides_service import get_writing_guides_by_lang_bundle

router = APIRouter()


def _hub_delivered_fields(rfp: models.RFP) -> dict[str, Any]:
    """통합 허브: 납품 패키지(JSON) 또는 레거시 단일 마크다운 미리보기용 컨텍스트."""
    raw_pkg = parse_delivered_code_payload(getattr(rfp, "delivered_code_payload", None))
    has_pkg = bool(raw_pkg and delivered_package_has_body(raw_pkg))
    dc_ready = (getattr(rfp, "delivered_code_status", None) or "").strip() == "ready"
    txt = (getattr(rfp, "delivered_code_text", None) or "").strip()
    delivered_package = raw_pkg if has_pkg else None
    delivered_code_html = ""
    if dc_ready and txt and not has_pkg:
        delivered_code_html = _interview_views._markdown_to_html(rfp.delivered_code_text or "")
    impl_html = ""
    test_html = ""
    if delivered_package:
        impl_html = _interview_views._markdown_to_html(
            delivered_package.get("implementation_guide_md") or ""
        )
        test_html = _interview_views._markdown_to_html(
            delivered_package.get("test_scenarios_md") or ""
        )
    has_delivered_preview = bool(dc_ready and (has_pkg or bool(txt)))
    return {
        "delivered_package": delivered_package,
        "delivered_code_html": delivered_code_html,
        "delivered_impl_guide_html": impl_html,
        "delivered_test_scenarios_html": test_html,
        "has_delivered_preview": has_delivered_preview,
    }


def _rfp_missing_core_field_labels(
    title: str,
    program_id: str,
    sap_modules: list,
    dev_types: list,
    description: str,
    min_description_chars: int | None = None,
) -> list[str]:
    """임시저장·제출 공통 필수(요청 제목, 프로그램 ID, 모듈·유형, 요구사항 분량)."""
    min_chars = (
        min_description_chars
        if min_description_chars is not None
        else MIN_RFP_DESCRIPTION_CHARS
    )
    miss: list[str] = []
    if not (title or "").strip():
        miss.append("요청 제목")
    if not (program_id or "").strip():
        miss.append("프로그램 ID")
    if not sap_modules:
        miss.append("SAP 모듈(1개 이상)")
    if not dev_types:
        miss.append("개발 유형(1개 이상)")
    if len((description or "").strip()) < min_chars:
        miss.append(f"요구사항 자유 기술(공백 제외 {min_chars}자 이상)")
    return miss


def _rfp_core_fields_incomplete_response(request: Request, missing: list[str]) -> Response:
    msg = "다음 필수 항목을 입력해 주세요: " + " · ".join(missing) + "."
    return templates.TemplateResponse(
        request,
        "form_validation_error.html",
        {"message": msg},
        status_code=422,
    )


class RfpSuggestFieldIn(BaseModel):
    kind: str = Field(..., description="title | program_id")
    description: str = ""
    title: str = ""


def _billing_flash_message(checkout: str | None) -> str | None:
    key = (checkout or "").strip().lower()
    if not key:
        return None
    return {
        "success": "결제가 완료되었습니다. 개발 의뢰가 활성화되었습니다.",
        "cancelled": "결제 창을 닫았습니다. 필요할 때 다시 시도할 수 있습니다.",
        "error": "결제 시작 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        "unconfigured": "결제 시스템이 아직 설정되지 않았습니다.",
        "missing_session": "결제 세션 정보가 없습니다.",
        "verify_failed": "결제 확인에 실패했습니다. 고객 지원에 문의해 주세요.",
    }.get(key)


def _ref_code_initial_from_rfp(rfp: Any) -> Optional[dict]:
    if not rfp:
        return None
    raw = getattr(rfp, "reference_code_payload", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

# Railway 웹 프로세스 로컬 디스크(ephemeral)·/tmp 는 재배포 시 사라질 수 있습니다.
# 첨부 바이너리는 Postgres에 넣지 않고, 여기 또는 R2(r2_storage)에 저장·DB에는 경로만 JSON 저장.
UPLOAD_DIR = (
    "/tmp/sap_uploads"
    if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
    else "uploads"
)
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_RFP_ATTACHMENTS = 5


async def _build_attachment_entries_from_uploads(
    user_id: int,
    uploads: List[UploadFile],
    notes: list[str],
) -> tuple[list[dict] | None, str | None]:
    """업로드 파일 목록을 저장하고 entries 생성. (None, err_key) 오류 시."""
    entries: list[dict] = []
    for i, up in enumerate(uploads):
        if not up.filename:
            continue
        if len(entries) >= MAX_RFP_ATTACHMENTS:
            return None, "too_many_attachments"
        ext = os.path.splitext(up.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None, "invalid_file"
        try:
            raw = await _read_upload_limited(up)
        except ValueError:
            return None, "file_too_large"
        if len(raw) == 0:
            return None, "empty_attachment"
        path, fname = _store_rfp_file(user_id, ext, raw, up.filename)
        note = (notes[i] if i < len(notes) else "") or ""
        entries.append({"path": path, "filename": fname, "note": note.strip()})
    return entries, None


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """멀티파트 업로드 본문을 읽습니다.

    일부 환경에서 비동기 read() 첫 호출만 빈 값이 되는 경우가 있어 seek(0) 후 단일 read() 시도,
    그래도 비면 동기 파일 객체에서 재시도합니다. (PostgreSQL에는 바이너리가 들어가지 않고 R2 또는 로컬 경로만 저장.)
    """

    async def _async_read_all() -> bytes:
        try:
            await upload.seek(0)
        except Exception:
            pass
        return await upload.read()

    raw = await _async_read_all()
    if len(raw) > MAX_FILE_SIZE_BYTES:
        raise ValueError("file_too_large")

    if not raw and getattr(upload, "file", None) is not None:
        def _sync_read_all() -> bytes:
            uf = upload.file
            try:
                uf.seek(0)
            except Exception:
                pass
            try:
                return uf.read() or b""
            except Exception:
                return b""

        raw = await run_in_threadpool(_sync_read_all)

    if len(raw) > MAX_FILE_SIZE_BYTES:
        raise ValueError("file_too_large")
    return raw


def _save_attachment_local(user_id: int, ext: str, data: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"rfp_{user_id}_{int(__import__('time').time())}{ext}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _store_rfp_file(user_id: int, ext: str, data: bytes, original_filename: str) -> Tuple[str, str]:
    """Persist bytes to R2 (if configured) or local UPLOAD_DIR; returns (file_path, file_name)."""
    ct = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    if r2_storage.is_configured():
        uri = r2_storage.upload_bytes(user_id, ext, data, ct)
        return uri, original_filename
    return _save_attachment_local(user_id, ext, data), original_filename


def duplicate_attachment_entries(entries: list[dict], *, user_id: int) -> list[dict]:
    """첨부를 새 저장 경로로 복제합니다(복사본이 원본 삭제에 영향받지 않도록). 읽기 실패 항목은 건너뜁니다."""
    out: list[dict] = []
    for ent in entries or []:
        if not isinstance(ent, dict):
            continue
        path = ent.get("path")
        fname = (ent.get("filename") or "attachment").strip() or "attachment"
        note = (ent.get("note") or "").strip()
        if not path:
            continue
        raw = r2_storage.read_bytes_from_ref(path)
        if not raw:
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext = ".bin"
        new_path, new_fname = _store_rfp_file(user_id, ext, raw, fname)
        out.append({"path": new_path, "filename": new_fname, "note": note})
    return out


def _rfp_attachment_entries(rfp: models.RFP) -> list[dict]:
    """attachments_json 우선, 없으면 레거시 단일 file_path."""
    if getattr(rfp, "attachments_json", None):
        try:
            data = json.loads(rfp.attachments_json)
            if isinstance(data, list) and data:
                return [x for x in data if isinstance(x, dict) and x.get("path")]
        except Exception:
            pass
    if rfp.file_path:
        return [{
            "path": rfp.file_path,
            "filename": rfp.file_name or os.path.basename(rfp.file_path),
            "note": "",
        }]
    return []


def _rfp_offer_rows(db: Session, rfp_id: int) -> list[models.RequestOffer]:
    return (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.request_kind == "rfp",
            models.RequestOffer.request_id == rfp_id,
        )
        .order_by(models.RequestOffer.created_at.desc())
        .all()
    )


def _set_rfp_attachments(rfp: models.RFP, entries: list[dict]) -> None:
    """레거시 file_path/file_name은 첫 번째 첨부와 동기화."""
    if not entries:
        rfp.attachments_json = None
        rfp.file_path = None
        rfp.file_name = None
        return
    rfp.attachments_json = json.dumps(entries, ensure_ascii=False)
    rfp.file_path = entries[0]["path"]
    rfp.file_name = entries[0]["filename"]


def _remove_stored_file(file_path: Optional[str]) -> None:
    if not file_path:
        return
    r2_storage.delete_if_r2_uri(file_path)
    if file_path.startswith(r2_storage.R2_PREFIX):
        return
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
    except OSError:
        pass


def _rfp_form_ctx(
    request: Request,
    user,
    modules,
    devtypes,
    writing_tip: str,
    db: Session,
    error: str | None = None,
    form: dict | None = None,
    rfp=None,
    edit_mode: bool = False,
    attachment_entries: list | None = None,
):
    ctx = {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "writing_tip": writing_tip,
        "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
        "error": error,
        "form": form,
        "rfp": rfp,
        "edit_mode": edit_mode,
    }
    if attachment_entries is not None:
        ctx["attachment_entries"] = attachment_entries
    elif rfp is not None:
        ctx["attachment_entries"] = _rfp_attachment_entries(rfp)
    else:
        ctx["attachment_entries"] = []
    ctx["ref_code_initial"] = _ref_code_initial_from_rfp(rfp)
    return ctx


def _get_modules_devtypes(db: Session):
    from ..devtype_catalog import active_abap_devtypes

    modules = db.query(models.SAPModule).filter(models.SAPModule.is_active == True).order_by(models.SAPModule.sort_order).all()
    devtypes = active_abap_devtypes(db)
    return modules, devtypes


@router.get("/rfp/new", response_class=HTMLResponse)
def rfp_form(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""
    return templates.TemplateResponse(
        request,
        "rfp_form.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "devtypes": devtypes,
            "writing_tip": writing_tip,
            "attachment_entries": [],
            "ref_code_initial": None,
            "edit_mode": False,
            "ai_inquiry": {
                "mode": "teaser",
                "float_id": "rfp-new-ai-teaser",
                "teaser_i18n": "chat.formAiTeaserRfp",
            },
            "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
        },
    )


@router.post("/rfp/api/suggest-field")
async def rfp_api_suggest_field(
    request: Request,
    body: RfpSuggestFieldIn,
    db: Session = Depends(get_db),
):
    """폼용: 요구사항 요약 제목(원문 언어 유지) / 요청 제목 기반 Z 프로그램 ID (Gemini)."""
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
    k = (body.kind or "").strip().lower()
    try:
        if k == "title":
            if not description_sufficient_for_suggest(body.description):
                return JSONResponse({"ok": False, "error": "description_insufficient"}, status_code=400)
            out = await run_in_threadpool(
                lambda: suggest_title_from_description((body.description or "").strip())
            )
            return JSONResponse({"ok": True, "title": out})
        if k == "program_id":
            if not description_sufficient_for_suggest(body.description):
                return JSONResponse({"ok": False, "error": "description_insufficient"}, status_code=400)
            tit = (body.title or "").strip()
            if not tit:
                return JSONResponse({"ok": False, "error": "title_empty"}, status_code=400)
            pid = await run_in_threadpool(lambda: suggest_program_id_from_title(tit))
            return JSONResponse({"ok": True, "program_id": pid, "mirror_transaction": True})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    except Exception:
        return JSONResponse({"ok": False, "error": "llm_failed"}, status_code=503)
    return JSONResponse({"ok": False, "error": "invalid_kind"}, status_code=400)


@router.post("/rfp/new")
async def submit_rfp(
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
    description: str = Form(""),
    description_format: str = Form("html"),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    save_action: str = Form("submit"),
    reference_code_json: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    is_draft = (save_action.strip().lower() == "draft")
    desc_fmt = (description_format or "html").strip().lower()
    desc_plain = _description_plain_for_validate(description, desc_fmt)
    notes_in = [note_0, note_1, note_2, note_3, note_4]

    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    def _form_dict():
        return {
            "program_id": program_id,
            "transaction_code": transaction_code,
            "title": title,
            "description": description,
            "description_format": desc_fmt,
            "sap_modules": sap_modules,
            "dev_types": dev_types,
            "notes": notes_in,
        }

    # 최대 3개 초과 검증
    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="max_selection",
                form=_form_dict(),
            ),
            status_code=400,
        )

    miss = _rfp_missing_core_field_labels(
        title,
        program_id,
        sap_modules,
        dev_types,
        desc_plain,
        min_description_chars=0 if is_draft else None,
    )
    if miss:
        return _rfp_core_fields_incomplete_response(request, miss)

    pid, perr = sap_fields.validate_program_id(program_id, required=True)
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error=err_key,
                form=_form_dict(),
            ),
            status_code=400,
        )

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error=err_key,
                form=_form_dict(),
            ),
            status_code=400,
        )

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="too_many_attachments",
                form=_form_dict(),
            ),
            status_code=400,
        )

    att_entries: list[dict] = []
    if n_uploads:
        att_entries, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                _rfp_form_ctx(
                    request, user, modules, devtypes, writing_tip, db,
                    error=err_a,
                    form=_form_dict(),
                ),
                status_code=400,
            )

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="reference_code_too_large",
                form=_form_dict(),
            ),
            status_code=400,
        )

    qerr = try_consume_monthly(db, user, METRIC_DEV_REQUEST, 1)
    if qerr == "disabled":
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="subscription_dev_request_disabled",
                form=_form_dict(),
            ),
            status_code=400,
        )
    if qerr == "monthly_limit":
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="subscription_dev_request_limit",
                form=_form_dict(),
            ),
            status_code=400,
        )

    rfp = models.RFP(
        user_id=user.id,
        program_id=pid,
        transaction_code=tc,
        title=title.strip(),
        sap_modules=",".join(sap_modules) if sap_modules else "",
        dev_types=",".join(dev_types) if dev_types else "",
        description="",
        description_format="plain",
        status="draft" if is_draft else "submitted",
        interview_status="pending",
        workflow_origin="direct",
        reference_code_payload=norm_ref,
    )
    _set_rfp_attachments(rfp, att_entries)
    db.add(rfp)
    try:
        db.flush()
        body_err = apply_requirement_body(rfp, user, description, desc_fmt, "rfp")
        if body_err:
            db.rollback()
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                _rfp_form_ctx(
                    request, user, modules, devtypes, writing_tip, db,
                    error=body_err,
                    form=_form_dict(),
                ),
                status_code=400,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(rfp)
    if is_draft:
        return RedirectResponse(url=f"/rfp/{rfp.id}/edit", status_code=302)
    return RedirectResponse(url=f"/rfp/{rfp.id}/success", status_code=302)


@router.get("/rfp/{rfp_id}/success", response_class=HTMLResponse)
def rfp_success(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "rfp_success.html", {"user": user, "rfp": rfp})


@router.get("/rfp/{rfp_id}/attachment")
def rfp_download_attachment(
    rfp_id: int,
    request: Request,
    idx: int = 0,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="rfp",
        request_id=rfp_id,
        owner_user_id=int(rfp.user_id),
    ):
        return RedirectResponse(url="/", status_code=302)
    entries = _rfp_attachment_entries(rfp)
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


@router.get("/rfp/{rfp_id}/requirement-inline")
def rfp_requirement_inline_image(
    rfp_id: int,
    request: Request,
    iid: str = "",
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_hub_readonly_embed(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    key = (iid or "").strip()
    if not key:
        return RedirectResponse(url=f"/rfp/{rfp_id}", status_code=302)
    ent = resolve_inline_entry(rfp, key)
    return inline_image_response(ent=ent, redirect_url=f"/rfp/{rfp_id}")


def _collect_rfp_unified_hub_ctx(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks | None,
    *,
    phase: str | None,
    view: str | None,
    checkout: str | None,
    db: Session,
    readonly_console: bool,
) -> RedirectResponse | dict[str, Any]:
    """Shared context for 신규 개발 통합 허브 페이지와 요청 Console 조회 전용 뷰."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if readonly_console:
        rfp = rfp_for_hub_readonly_embed(
            db,
            user=user,
            rfp_id=rfp_id,
            load_messages=True,
            load_fs_supplements=True,
            load_followup_messages=False,
        )
    else:
        rfp = rfp_for_owner_or_admin(
            db,
            user=user,
            rfp_id=rfp_id,
            load_messages=True,
            load_fs_supplements=True,
            load_followup_messages=True,
        )
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    requested_phase = normalize_rfp_hub_phase(phase)
    wo_hub = (getattr(rfp, "workflow_origin", None) or "").strip().lower()
    hub_skip_interview = wo_hub == "abap_analysis"
    if hub_skip_interview and requested_phase == "interview":
        if readonly_console:
            ro_qs: dict[str, str] = {"phase": "proposal"}
            if (request.query_params.get("embed") or "").strip() == "1":
                ro_qs["embed"] = "1"
            return RedirectResponse(
                url=f"/rfp/{rfp_id}/console-readonly?{urlencode(ro_qs)}",
                status_code=302,
            )
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)

    if readonly_console and (rfp.status or "").strip() == "draft":
        requested_phase = normalize_rfp_hub_phase("request")

    view_summary = (view or "").strip().lower() == "summary" and requested_phase == "interview"

    if not readonly_console and (rfp.status or "").strip() == "draft" and requested_phase != "request":
        return RedirectResponse(url=f"/rfp/{rfp_id}/edit", status_code=302)

    display_phase = requested_phase
    hub_embedded = False
    hub_proposal_generating_override = False
    ws_out = None

    if (not readonly_console) and requested_phase == "interview" and not view_summary:
        ws_out = _interview_views.serve_interview_workspace(
            request, db, user, rfp, background_tasks
        )
        db.refresh(rfp)
        if ws_out.kind == "redirect":
            return RedirectResponse(url=ws_out.redirect_url or "/", status_code=302)
        if ws_out.kind == "generating":
            display_phase = "proposal"
            hub_proposal_generating_override = True
        elif ws_out.kind == "wizard" and ws_out.wizard_ctx:
            hub_embedded = True
            display_phase = "interview"

    if requested_phase in ("fs", "devcode"):
        if not user_can_access_fs_hub(user, rfp):
            return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=302)

    groups = reference_code_program_groups_for_tabs(rfp.reference_code_payload)
    ref_section_count = sum(len(g["sections"]) for g in groups) if groups else 0
    dc_s = (rfp.delivered_code_status or "none").strip() or "none"

    fs_html = ""
    if (rfp.fs_status or "") == "ready" and (rfp.fs_text or "").strip():
        fs_html = _interview_views._markdown_to_html(rfp.fs_text)

    delivered_fields = _hub_delivered_fields(rfp)

    fs_stat = (rfp.fs_status or "none").strip() or "none"
    dc_stat = dc_s
    fs_busy = fs_stat == "generating"
    dc_busy = dc_stat == "generating"
    gen_busy = fs_busy or dc_busy

    can_start_delivered_code = False
    can_operate_delivery = user_can_operate_delivery(user)
    if can_operate_delivery:
        fs_body, _ = resolved_fs_markdown_for_codegen(db, rfp)
        can_start_delivered_code = bool(fs_body and fs_body.strip()) and (
            (rfp.delivered_code_status or "").strip() != "generating"
        )

    answered_sorted = sorted(
        [m for m in rfp.messages if m.is_answered],
        key=lambda x: (x.round_number, x.id),
    )
    interview_summary_messages = _interview_views._messages_to_list(answered_sorted)
    proposal_round_messages = interview_summary_messages

    hub_proposal_generating = hub_proposal_generating_override or (
        (rfp.interview_status or "") == "generating_proposal"
    )

    proposal_html = ""
    if (rfp.interview_status or "") == "completed" and (rfp.proposal_text or "").strip():
        proposal_html = _interview_views._markdown_to_html(
            wrap_unbracketed_agent_names(rfp.proposal_text or "")
        )

    tabs_base_id = f"rfp-ref-src-{rfp.id}"

    owner = None
    if getattr(user, "is_admin", False) or (
        readonly_console and getattr(user, "is_consultant", False)
    ) or consultant_has_request_offer(
        db, consultant_user_id=user.id, request_kind="rfp", request_id=rfp.id
    ):
        owner = db.query(models.User).filter(models.User.id == rfp.user_id).first()

    delete_blocked = (request.query_params.get("delete_blocked") or "").strip()
    qe = (request.query_params.get("quota_err") or "").strip()
    subscription_quota_flash = None
    if qe == "duplicate_limit":
        subscription_quota_flash = "이번 달(UTC) 요청 복사 한도에 도달했습니다."
    elif qe == "dev_request_limit":
        subscription_quota_flash = "이번 달(UTC) 개발 요청 생성 한도에 도달했습니다."
    elif qe == "dev_proposal_limit":
        subscription_quota_flash = "이번 달(UTC) 개발 제안서 생성 한도에 도달했습니다."
    elif qe == "proposal_regen_limit":
        subscription_quota_flash = "이 요청에서 제안서 재생성 허용 횟수에 도달했습니다."
    elif qe == "dev_proposal_disabled":
        subscription_quota_flash = "현재 플랜에서 개발 제안서 생성을 사용할 수 없습니다."
    elif qe == "proposal_regen_disabled":
        subscription_quota_flash = "현재 플랜에서 제안서 재생성을 사용할 수 없습니다."

    proposal_scripts = (not readonly_console) and bool(proposal_html) and not hub_proposal_generating

    vis_offers = visible_request_offers_for_viewer(
        _rfp_offer_rows(db, rfp.id),
        viewer=user,
        owner_user_id=rfp.user_id,
        privileged_operator=bool(getattr(user, "is_admin", False)),
    )

    code_asset_unlocked = user_may_copy_download_request_assets(
        db,
        user,
        request_kind="rfp",
        request_id=rfp_id,
        owner_user_id=int(rfp.user_id),
    )

    hub_rfp_ai_chat_enabled = False
    if not readonly_console:
        hub_rfp_ai_chat_enabled = (
            int(user.id) == int(rfp.user_id)
            or getattr(user, "is_admin", False)
            or (
                getattr(user, "is_consultant", False)
                and consultant_is_matched_on_request(
                    db, consultant_user_id=user.id, request_kind="rfp", request_id=int(rfp.id)
                )
            )
        )

    hub_abap_proposal_start_eligible = bool(
        hub_skip_interview
        and (not readonly_console)
        and user
        and int(user.id) == int(rfp.user_id)
        and _interview_views._interview_has_substance(rfp)
        and not (rfp.proposal_text or "").strip()
        and (rfp.interview_status or "") != "generating_proposal"
    )

    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "rfp": rfp,
        "owner": owner,
        "code_asset_unlocked": code_asset_unlocked,
        "delete_blocked_reason": delete_blocked,
        "subscription_quota_flash": subscription_quota_flash,
        "hub_phase_open": display_phase,
        "hub_skip_interview": hub_skip_interview,
        "hub_abap_proposal_start_eligible": hub_abap_proposal_start_eligible,
        "hub_embedded": hub_embedded,
        "attachment_entries": _rfp_attachment_entries(rfp),
        "interview_summary_messages": interview_summary_messages,
        "proposal_round_messages": proposal_round_messages,
        "hub_proposal_generating": hub_proposal_generating,
        "proposal_html": proposal_html,
        "billing_flash": _billing_flash_message(checkout),
        "paid_engagement_active": paid_engagement_is_active(rfp),
        "rfp_eligible_for_checkout": rfp_eligible_for_stripe_checkout(rfp),
        "stripe_checkout_ready": stripe_keys_configured(),
        "fs_html": fs_html,
        "fs_stat": fs_stat,
        "dc_stat": dc_stat,
        "fs_busy": fs_busy,
        "dc_busy": dc_busy,
        "gen_busy": gen_busy,
        "can_start_delivered_code": can_start_delivered_code,
        "can_operate_delivery": can_operate_delivery,
        "source_program_groups": groups,
        "reference_section_count": ref_section_count,
        "tabs_base_id": tabs_base_id,
        "hub_include_proposal_scripts": proposal_scripts,
        "request_offers": vis_offers,
        "request_offer_can_match": bool(user and rfp and user.id == rfp.user_id and not readonly_console),
        "request_offer_profile_url_builder": lambda offer_id: f"/rfp/{rfp.id}/offers/{int(offer_id)}/profile",
        "request_offer_match_url_builder": lambda offer_id: f"/rfp/{rfp.id}/offers/{int(offer_id)}/match",
        "request_offer_inquiries_by_offer_id": inquiries_by_offer_id(db, [int(o.id) for o in vis_offers]),
        "request_offer_inquiry_url_builder": lambda offer_id: f"/rfp/{rfp.id}/offers/{int(offer_id)}/inquiry",
        "request_offer_can_inquire": bool(user and rfp and user.id == rfp.user_id and not readonly_console),
        "offer_inquiry_request_detail_url": public_request_url(
            request, f"/rfp/{rfp.id}?phase=proposal"
        ),
        "offer_inquiry_err": (request.query_params.get("offer_inquiry_err") or "").strip(),
        "offer_inquiry_ok": (request.query_params.get("offer_inquiry_ok") or "").strip() == "1",
        "offer_inquiry_reply_err": (request.query_params.get("offer_inquiry_reply_err") or "").strip(),
        "offer_inquiry_reply_ok": (request.query_params.get("offer_inquiry_reply_ok") or "").strip() == "1",
        "request_offer_inquiry_reply_url_builder": lambda offer_id: f"/rfp/{rfp.id}/offers/{int(offer_id)}/inquiry-reply",
        "hub_rfp_ai_chat_enabled": hub_rfp_ai_chat_enabled,
        "hub_readonly_return_url": (
            f"/rfp/{rfp.id}/console-readonly?phase={display_phase}" if readonly_console else None
        ),
    }
    ctx.update(delivered_fields)
    ctx.update(requirement_display_ctx(rfp, "rfp", int(rfp.id)))

    if hub_embedded and ws_out is not None and ws_out.kind == "wizard" and ws_out.wizard_ctx:
        ctx.update(ws_out.wizard_ctx)

    if not readonly_console:
        wf_ctx = load_workflow_abap_mirror_context(db, user, rfp)
        if wf_ctx:
            ctx.update(wf_ctx)

    if readonly_console:
        snap = ai_inquiry_snapshot(db, user, "rfp", rfp.id)
        ctx.update(
            {
                "rfp_followup_turns": [],
                "rfp_chat_limit_reached": snap["reached"],
                "rfp_chat_error": None,
                "rfp_followup_max_user": snap["cap"],
                "rfp_ai_inquiry_unlimited": snap["unlimited"],
            }
        )
    else:
        follow_raw = sorted(
            list(rfp.followup_messages or []),
            key=lambda m: (
                followup_created_at_sort_key(m, fallback=rfp.created_at),
                getattr(m, "id", 0) or 0,
            ),
        )
        follow_msgs = filter_followup_messages_for_viewer(
            follow_raw,
            request_owner_id=int(rfp.user_id),
            viewer_user_id=int(user.id),
            viewer_is_admin=bool(getattr(user, "is_admin", False)),
        )
        followup_turns = pair_followup_turn_messages(follow_msgs)
        snap = ai_inquiry_snapshot(db, user, "rfp", rfp.id)
        rfp_chat_error = (request.query_params.get("chat_err") or "").strip() or None
        ctx.update(
            {
                "rfp_followup_turns": followup_turns,
                "rfp_chat_limit_reached": snap["reached"],
                "rfp_chat_error": rfp_chat_error,
                "rfp_followup_max_user": snap["cap"],
                "rfp_ai_inquiry_unlimited": snap["unlimited"],
            }
        )

    return ctx


@router.get("/rfp/{rfp_id}/console-readonly", response_class=HTMLResponse)
def rfp_unified_hub_console_readonly(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    phase: str | None = None,
    view: str | None = None,
    checkout: str | None = None,
    db: Session = Depends(get_db),
):
    out = _collect_rfp_unified_hub_ctx(
        rfp_id,
        request,
        background_tasks,
        phase=phase,
        view=view,
        checkout=checkout,
        db=db,
        readonly_console=True,
    )
    if isinstance(out, RedirectResponse):
        return out
    out["layout_template"] = layout_template_from_embed_query(request)
    return templates.TemplateResponse(request, "rfp_unified_hub_readonly.html", out)


@router.get("/rfp/{rfp_id}", response_class=HTMLResponse)
def rfp_unified_hub(
    rfp_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    phase: str | None = None,
    view: str | None = None,
    checkout: str | None = None,
    db: Session = Depends(get_db),
):
    """신규 개발 통합 상세 — 요청·인터뷰·제안서·FS·개발코드 (단계별 details)."""
    out = _collect_rfp_unified_hub_ctx(
        rfp_id,
        request,
        background_tasks,
        phase=phase,
        view=view,
        checkout=checkout,
        db=db,
        readonly_console=False,
    )
    if isinstance(out, RedirectResponse):
        return out
    return templates.TemplateResponse(request, "rfp_unified_hub.html", out)


def _rfp_ai_chat_redirect(rfp_id: int, return_to: str | None, chat_err: str | None = None) -> str:
    rt = (return_to or "hub").strip().lower()
    base = f"/rfp/{rfp_id}/edit" if rt == "edit" else f"/rfp/{rfp_id}"
    suffix = f"?chat_err={quote(chat_err)}" if chat_err else ""
    return f"{base}{suffix}#rfp-followup-chat"


@router.post("/rfp/{rfp_id}/offers/{offer_id}/match")
def rfp_offer_match(
    rfp_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/rfp", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "rfp",
            models.RequestOffer.request_id == rfp_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=proposal", status_code=303)
    if (offer.status or "") == "matched":
        offer.status = "offered"
        offer.matched_at = None
        offer.match_notice_pending = False
        db.add(offer)
        db.commit()
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=proposal", status_code=303)
    db.query(models.RequestOffer).filter(
        models.RequestOffer.request_kind == "rfp",
        models.RequestOffer.request_id == rfp_id,
    ).update(
        {"status": "offered", "matched_at": None, "match_notice_pending": False},
        synchronize_session=False,
    )
    offer.status = "matched"
    offer.matched_at = datetime.utcnow()
    offer.match_notice_pending = True
    db.add(offer)
    db.commit()
    title = (rfp.title or "").strip() or f"RFP #{rfp_id}"
    c = offer.consultant
    if c:
        notify_consultant_request_matched(
            request=request,
            consultant=c,
            request_kind="rfp",
            request_id=rfp_id,
            request_title=title,
        )
    return RedirectResponse(url=f"/rfp/{rfp_id}?phase=proposal", status_code=303)


@router.post("/rfp/{rfp_id}/offers/{offer_id}/inquiry")
def rfp_offer_inquiry_post(
    rfp_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/rfp", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "rfp",
            models.RequestOffer.request_id == rfp_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=303)
    title = (rfp.title or "").strip() or f"RFP #{rfp_id}"
    detail = public_request_url(request, f"/rfp/{rfp_id}?phase=proposal")
    err, _row = send_offer_inquiry_from_owner(
        db,
        request=request,
        author=user,
        offer=offer,
        consultant=offer.consultant,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    base = rfp_hub_url(rfp_id, "proposal")
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_ok=1", status_code=303)


@router.post("/rfp/{rfp_id}/offers/{offer_id}/inquiry-reply")
def rfp_offer_inquiry_reply_post(
    rfp_id: int,
    offer_id: int,
    request: Request,
    body: str = Form(""),
    return_hub: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not getattr(user, "is_consultant", False):
        return RedirectResponse(url="/", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id).first()
    if not rfp:
        return RedirectResponse(url="/rfp", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "rfp",
            models.RequestOffer.request_id == rfp_id,
        )
        .first()
    )
    if not offer:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=303)
    owner = db.query(models.User).filter(models.User.id == rfp.user_id).first()
    if not owner:
        return RedirectResponse(url=rfp_hub_url(rfp_id, "proposal"), status_code=303)
    title = (rfp.title or "").strip() or f"RFP #{rfp_id}"
    detail = public_request_url(request, f"/rfp/{rfp_id}?phase=proposal")
    err, _row = send_consultant_offer_inquiry_reply(
        db,
        request=request,
        consultant=user,
        offer=offer,
        owner=owner,
        request_title=title,
        request_detail_url=detail,
        body_raw=body,
    )
    safe = sanitize_console_readonly_return_url(return_hub)
    base = safe if safe else rfp_hub_url(rfp_id, "proposal")
    sep = "&" if "?" in base else "?"
    if err:
        return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_err={quote(err)}", status_code=303)
    return RedirectResponse(url=f"{base}{sep}offer_inquiry_reply_ok=1", status_code=303)


@router.get("/rfp/{rfp_id}/offers/{offer_id}/profile")
def rfp_offer_profile_download(
    rfp_id: int,
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/rfp", status_code=302)
    offer = (
        db.query(models.RequestOffer)
        .options(joinedload(models.RequestOffer.consultant))
        .filter(
            models.RequestOffer.id == offer_id,
            models.RequestOffer.request_kind == "rfp",
            models.RequestOffer.request_id == rfp_id,
        )
        .first()
    )
    if not offer or not offer.consultant:
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=request", status_code=302)
    path = (getattr(offer.consultant, "consultant_profile_file_path", None) or "").strip()
    fname = (getattr(offer.consultant, "consultant_profile_file_name", None) or "consultant_profile").strip() or "consultant_profile"
    if not path:
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=request", status_code=302)
    kind, ref = r2_storage.parse_storage_ref(path)
    if kind == "r2":
        if not r2_storage.is_configured():
            return RedirectResponse(url=f"/rfp/{rfp_id}?phase=request", status_code=302)
        return RedirectResponse(url=r2_storage.presigned_get_url(ref, fname), status_code=302)
    if not os.path.isfile(ref):
        return RedirectResponse(url=f"/rfp/{rfp_id}?phase=request", status_code=302)
    return FileResponse(ref, filename=fname)


@router.post("/rfp/{rfp_id}/chat")
def rfp_hub_chat_post(
    rfp_id: int,
    request: Request,
    message: str = Form(""),
    return_to: str = Form("hub"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_owned_only(db, user_id=user.id, rfp_id=rfp_id)
    if not rfp:
        rfp = rfp_for_owner_or_admin(
            db,
            user=user,
            rfp_id=rfp_id,
            load_messages=False,
            load_fs_supplements=False,
            load_followup_messages=False,
        )
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    allowed = int(user.id) == int(rfp.user_id) or getattr(user, "is_admin", False) or (
        getattr(user, "is_consultant", False)
        and consultant_is_matched_on_request(
            db, consultant_user_id=user.id, request_kind="rfp", request_id=int(rfp_id)
        )
    )
    if not allowed:
        return RedirectResponse(url="/", status_code=302)

    msg, verr = validate_rfp_user_message(message)
    if verr:
        return RedirectResponse(
            url=_rfp_ai_chat_redirect(rfp_id, return_to, verr),
            status_code=303,
        )

    used_ai = get_ai_inquiry_used(db, user.id, "rfp", rfp.id)
    cap = ai_inquiry_snapshot(db, user, "rfp", rfp.id)["cap"]
    if ai_inquiry_limit_reached(cap, used_ai):
        return RedirectResponse(
            url=_rfp_ai_chat_redirect(rfp_id, return_to, "후속 질문은 상한에 도달했습니다."),
            status_code=303,
        )

    prior_all = (
        db.query(models.RfpFollowupMessage)
        .filter(models.RfpFollowupMessage.rfp_id == rfp.id)
        .order_by(models.RfpFollowupMessage.created_at.asc())
        .all()
    )
    prior = filter_followup_messages_for_viewer(
        prior_all,
        request_owner_id=int(rfp.user_id),
        viewer_user_id=int(user.id),
        viewer_is_admin=bool(getattr(user, "is_admin", False)),
    )

    rfp_ctx = (
        db.query(models.RFP)
        .options(joinedload(models.RFP.messages))
        .filter(models.RFP.id == rfp_id, models.RFP.user_id == rfp.user_id)
        .first()
    )
    if not rfp_ctx:
        return RedirectResponse(url="/", status_code=302)

    try:
        ctx_block = rfp_followup_context_block(
            db=db,
            rfp=rfp_ctx,
            attachment_entries=_rfp_attachment_entries(rfp_ctx),
        )
        reply = generate_rfp_followup_reply(
            context_block=ctx_block,
            history_messages=prior,
            user_question=msg,
        )
    except Exception:
        reply = "응답을 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    tid = int(user.id)
    db.add(models.RfpFollowupMessage(rfp_id=rfp.id, role="user", content=msg, thread_user_id=tid))
    db.add(
        models.RfpFollowupMessage(rfp_id=rfp.id, role="assistant", content=reply, thread_user_id=tid)
    )
    if not getattr(user, "is_admin", False):
        record_ai_inquiry_user_turn(db, user.id, "rfp", rfp.id, ledger_after=used_ai + 1)
    db.commit()
    return RedirectResponse(url=_rfp_ai_chat_redirect(rfp_id, return_to), status_code=303)


@router.get("/rfp/{rfp_id}/request", response_class=HTMLResponse)
def rfp_request_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """레거시 URL → 통합 허브 요청 단계."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "request"), status_code=302)


@router.get("/rfp/{rfp_id}/dev-code", response_class=HTMLResponse)
def rfp_dev_code_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """레거시 URL → 통합 허브 개발코드 단계."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "devcode"), status_code=302)


@router.get("/rfp/{rfp_id}/fs", response_class=HTMLResponse)
def rfp_fs_view_page(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """레거시 URL → 통합 허브 FS 단계."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=rfp_hub_url(rfp_id, "fs"), status_code=302)


@router.get("/rfp/{rfp_id}/paid-generation-status")
def rfp_paid_generation_status(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """FS·납품 코드 생성 진행 여부 폴링(회원·관리자)."""
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return JSONResponse(
        {
            "fs_status": getattr(rfp, "fs_status", None) or "none",
            "delivered_code_status": getattr(rfp, "delivered_code_status", None) or "none",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/rfp/{rfp_id}/fs/download")
def rfp_fs_download(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return RedirectResponse(url="/", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="rfp",
        request_id=rfp_id,
        owner_user_id=int(rfp.user_id),
    ):
        return RedirectResponse(url="/", status_code=302)
    if (rfp.fs_status or "") != "ready" or not (rfp.fs_text or "").strip():
        return RedirectResponse(url=rfp_hub_url(rfp_id, "fs"), status_code=302)
    body = (rfp.fs_text or "").encode("utf-8")
    fname = fs_md_download_basename(getattr(rfp, "program_id", None), getattr(rfp, "title", None))
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )


@router.get("/rfp/{rfp_id}/delivered-code/download")
def rfp_delivered_code_download(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_for_owner_or_admin(db, user=user, rfp_id=rfp_id, load_messages=False)
    if not rfp or not user_can_access_fs_hub(user, rfp):
        return RedirectResponse(url="/", status_code=302)
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind="rfp",
        request_id=rfp_id,
        owner_user_id=int(rfp.user_id),
    ):
        return RedirectResponse(url="/", status_code=302)
    if not rfp_delivered_body_ready(rfp):
        return RedirectResponse(url=rfp_hub_url(rfp_id, "fs"), status_code=302)
    pkg = parse_delivered_code_payload(getattr(rfp, "delivered_code_payload", None))
    if pkg and delivered_package_has_body(pkg):
        buf = io.BytesIO()
        used_names: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "IMPLEMENTATION_GUIDE.md",
                (pkg.get("implementation_guide_md") or "").encode("utf-8"),
            )
            zf.writestr(
                "TEST_SCENARIOS.md",
                (pkg.get("test_scenarios_md") or "").encode("utf-8"),
            )
            for idx, sl in enumerate(pkg.get("slots") or []):
                if not isinstance(sl, dict):
                    continue
                base_fn = (str(sl.get("filename") or f"slot_{idx + 1}.abap")).strip() or f"slot_{idx + 1}.abap"
                fn = base_fn
                if fn in used_names:
                    stem = base_fn.rsplit(".", 1)[0] if "." in base_fn else base_fn
                    ext = base_fn.rsplit(".", 1)[-1] if "." in base_fn else "abap"
                    fn = f"{idx + 1:02d}_{stem}.{ext}"
                used_names.add(fn)
                zf.writestr(fn, (sl.get("source") or "").encode("utf-8"))
        body = buf.getvalue()
        fname = delivered_code_zip_basename(getattr(rfp, "program_id", None), getattr(rfp, "title", None))
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": content_disposition_attachment(fname)},
        )
    body = (rfp.delivered_code_text or "").encode("utf-8")
    fname = delivered_abap_download_basename(getattr(rfp, "program_id", None), getattr(rfp, "title", None))
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )


@router.post("/rfp/{rfp_id}/duplicate-request")
def rfp_duplicate_request(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    """요청 필드만 복사한 새 임시저장 건을 현재 로그인 사용자 계정으로 만들고 수정 폼으로 이동합니다."""
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = rfp_owned_only(db, user_id=user.id, rfp_id=rfp_id)
    if not rfp:
        return RedirectResponse(url="/", status_code=302)
    from ..subscription_quota import consume_monthly, monthly_quota_exceeded

    if monthly_quota_exceeded(db, user, METRIC_REQUEST_DUPLICATE, 1):
        return RedirectResponse(url=f"/rfp/{rfp_id}?quota_err=duplicate_limit", status_code=302)
    if monthly_quota_exceeded(db, user, METRIC_DEV_REQUEST, 1):
        return RedirectResponse(url=f"/rfp/{rfp_id}?quota_err=dev_request_limit", status_code=302)
    consume_monthly(db, user, METRIC_REQUEST_DUPLICATE, 1)
    consume_monthly(db, user, METRIC_DEV_REQUEST, 1)
    entries = duplicate_attachment_entries(_rfp_attachment_entries(rfp), user_id=user.id)
    shots = duplicate_requirement_screenshots(
        requirement_screenshot_entries(rfp), user_id=user.id
    )
    title = (rfp.title or "").strip()
    if title and not title.endswith(" (복사)"):
        title = f"{title} (복사)"
    new_rfp = models.RFP(
        user_id=user.id,
        program_id=rfp.program_id,
        transaction_code=rfp.transaction_code,
        title=title or "복사된 요청",
        sap_modules=rfp.sap_modules,
        dev_types=rfp.dev_types,
        description=rfp.description or "",
        description_format=getattr(rfp, "description_format", None) or "plain",
        reference_code_payload=rfp.reference_code_payload,
        status="draft",
        interview_status="pending",
        workflow_origin="direct",
    )
    set_screenshot_entries(new_rfp, shots)
    _set_rfp_attachments(new_rfp, entries)
    db.add(new_rfp)
    db.commit()
    db.refresh(new_rfp)
    return RedirectResponse(url=f"/rfp/{new_rfp.id}/edit", status_code=302)


@router.post("/rfp/{rfp_id}/delete")
def rfp_delete(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    q = db.query(models.RFP).filter(models.RFP.id == rfp_id)
    if not user.is_admin:
        q = q.filter(models.RFP.user_id == user.id)
    rfp = q.first()
    if not rfp:
        return RedirectResponse(url="/services/abap", status_code=302)
    fs_st = (getattr(rfp, "fs_status", None) or "").strip() or "none"
    if fs_st != "none":
        return RedirectResponse(
            url=f"/rfp/{rfp_id}?delete_blocked=fs",
            status_code=302,
        )
    db.query(models.AbapAnalysisRequest).filter(
        models.AbapAnalysisRequest.workflow_rfp_id == rfp_id
    ).update({models.AbapAnalysisRequest.workflow_rfp_id: None}, synchronize_session=False)
    db.query(models.IntegrationRequest).filter(
        models.IntegrationRequest.workflow_rfp_id == rfp_id
    ).update({models.IntegrationRequest.workflow_rfp_id: None}, synchronize_session=False)
    for ent in _rfp_attachment_entries(rfp):
        _remove_stored_file(ent.get("path"))
    for sup in db.query(models.RfpFsSupplement).filter(models.RfpFsSupplement.rfp_id == rfp_id).all():
        _remove_stored_file(sup.stored_path)
    db.query(models.RFPMessage).filter(models.RFPMessage.rfp_id == rfp_id).delete(synchronize_session=False)
    db.query(models.RfpFsSupplement).filter(models.RfpFsSupplement.rfp_id == rfp_id).delete(
        synchronize_session=False
    )
    db.delete(rfp)
    db.commit()
    return RedirectResponse(url="/services/abap", status_code=302)


@router.get("/rfp/{rfp_id}/edit", response_class=HTMLResponse)
def rfp_edit_form(rfp_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""
    rfp_w = (
        db.query(models.RFP)
        .options(joinedload(models.RFP.followup_messages))
        .filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id)
        .first()
    )
    if not rfp_w:
        return RedirectResponse(url="/", status_code=302)
    follow_msgs = sorted(
        list(rfp_w.followup_messages or []),
        key=lambda m: (
            followup_created_at_sort_key(m, fallback=rfp_w.created_at),
            getattr(m, "id", 0) or 0,
        ),
    )
    followup_turns = pair_followup_turn_messages(follow_msgs)
    chat_err = (request.query_params.get("chat_err") or "").strip() or None
    snap_ed = ai_inquiry_snapshot(db, user, "rfp", rfp_w.id)
    ai_inquiry = {
        "mode": "live",
        "float_id": "rfp-followup-chat",
        "size_key": "rfp-followup-chat-size",
        "post_url": f"/rfp/{rfp_w.id}/chat",
        "return_to": "edit",
        "followup_turns": followup_turns,
        "chat_error": chat_err,
        "chat_limit_reached": snap_ed["reached"],
        "max_turns": snap_ed["max_turns_display"],
        "header_i18n": "chat.rfpHeaderTitle",
        "context_i18n": "chat.rfpContextHelp",
        "form_ready": True,
    }
    return templates.TemplateResponse(
        request,
        "rfp_form.html",
        {
            "request": request,
            "user": user,
            "rfp": rfp_w,
            "modules": modules,
            "devtypes": devtypes,
            "writing_tip": writing_tip,
            "edit_mode": True,
            "attachment_entries": _rfp_attachment_entries(rfp_w),
            "ref_code_initial": _ref_code_initial_from_rfp(rfp_w),
            "ai_inquiry": ai_inquiry,
            "writing_guides_by_lang": get_writing_guides_by_lang_bundle(db),
        },
    )


@router.post("/rfp/{rfp_id}/edit")
async def rfp_edit_submit(
    rfp_id: int,
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: List[str] = Form(default=[]),
    dev_types: List[str] = Form(default=[]),
    description: str = Form(""),
    description_format: str = Form("html"),
    attachments: List[UploadFile] = File(default=[]),
    note_0: str = Form(""),
    note_1: str = Form(""),
    note_2: str = Form(""),
    note_3: str = Form(""),
    note_4: str = Form(""),
    note_orig_0: str = Form(""),
    note_orig_1: str = Form(""),
    note_orig_2: str = Form(""),
    note_orig_3: str = Form(""),
    note_orig_4: str = Form(""),
    delete_0: str = Form(""),
    delete_1: str = Form(""),
    delete_2: str = Form(""),
    delete_3: str = Form(""),
    delete_4: str = Form(""),
    save_action: str = Form("submit"),
    reference_code_json: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rfp = db.query(models.RFP).filter(models.RFP.id == rfp_id, models.RFP.user_id == user.id).first()
    if not rfp:
        return RedirectResponse(url="/", status_code=302)

    is_draft = (save_action.strip().lower() == "draft")
    if rfp.status != "draft":
        is_draft = False

    desc_fmt = (description_format or "html").strip().lower()
    desc_plain = _description_plain_for_validate(description, desc_fmt)
    notes_in = [note_0, note_1, note_2, note_3, note_4]
    notes_orig = [note_orig_0, note_orig_1, note_orig_2, note_orig_3, note_orig_4]
    del_flags = [bool(delete_0), bool(delete_1), bool(delete_2), bool(delete_3), bool(delete_4)]

    modules, devtypes = _get_modules_devtypes(db)
    writing_tip_setting = db.query(models.SiteSettings).filter(models.SiteSettings.key == "rfp_writing_tip").first()
    writing_tip = writing_tip_setting.value if writing_tip_setting else ""

    def _form_dict():
        return {
            "program_id": program_id,
            "transaction_code": transaction_code,
            "title": title,
            "description": description,
            "description_format": desc_fmt,
            "sap_modules": sap_modules,
            "dev_types": dev_types,
            "notes": notes_in,
        }

    if len(sap_modules) > 3 or len(dev_types) > 3:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="max_selection",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    miss = _rfp_missing_core_field_labels(
        title,
        program_id,
        sap_modules,
        dev_types,
        desc_plain,
        min_description_chars=0 if is_draft else None,
    )
    if miss:
        return _rfp_core_fields_incomplete_response(request, miss)

    pid, perr = sap_fields.validate_program_id(program_id, required=True)
    if perr:
        err_key = {
            "required": "program_id_required",
            "too_long": "program_id_too_long",
            "no_ime_chars": "program_id_ime",
            "invalid_chars": "program_id_chars",
        }[perr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error=err_key,
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    tc, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        err_key = {
            "too_long": "transaction_code_too_long",
            "no_ime_chars": "transaction_code_ime",
            "invalid_chars": "transaction_code_chars",
        }[terr]
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error=err_key,
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    existing = _rfp_attachment_entries(rfp)
    kept: list[dict] = []
    for i, att in enumerate(existing):
        if i < len(del_flags) and del_flags[i]:
            _remove_stored_file(att.get("path"))
            continue
        note = (notes_orig[i] if i < len(notes_orig) else "") or ""
        kept.append({
            "path": att["path"],
            "filename": att.get("filename", ""),
            "note": note.strip(),
        })

    n_uploads = sum(1 for f in attachments if f.filename)
    if n_uploads > MAX_RFP_ATTACHMENTS:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="too_many_attachments",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    new_parts: list[dict] = []
    if n_uploads:
        new_parts, err_a = await _build_attachment_entries_from_uploads(user.id, attachments, notes_in)
        if err_a:
            return templates.TemplateResponse(
                request,
                "rfp_form.html",
                _rfp_form_ctx(
                    request, user, modules, devtypes, writing_tip, db,
                    error=err_a,
                    form=_form_dict(),
                    rfp=rfp,
                    edit_mode=True,
                ),
                status_code=400,
            )

    remaining = MAX_RFP_ATTACHMENTS - len(kept)
    if len(new_parts) > remaining:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="too_many_attachments",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    combined = kept + new_parts

    try:
        norm_ref = normalize_reference_code_payload(reference_code_json)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error="reference_code_too_large",
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )

    rfp.program_id = pid
    rfp.transaction_code = tc
    rfp.title = title.strip()
    rfp.sap_modules = ",".join(sap_modules) if sap_modules else ""
    rfp.dev_types = ",".join(dev_types) if dev_types else ""
    rfp.reference_code_payload = norm_ref
    if is_draft:
        rfp.status = "draft"
    else:
        rfp.status = "submitted"

    _set_rfp_attachments(rfp, combined)
    body_err = apply_requirement_body(rfp, user, description, desc_fmt, "rfp")
    if body_err:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "rfp_form.html",
            _rfp_form_ctx(
                request, user, modules, devtypes, writing_tip, db,
                error=body_err,
                form=_form_dict(),
                rfp=rfp,
                edit_mode=True,
            ),
            status_code=400,
        )
    db.commit()
    if is_draft:
        return RedirectResponse(url=f"/rfp/{rfp_id}/edit", status_code=302)
    return RedirectResponse(url=f"/rfp/{rfp_id}/success", status_code=302)


@router.patch("/rfp/{rfp_id}/reference-codes")
async def patch_rfp_reference_codes(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """편집 중 참고 ABAP JSON 자동 저장 (본 RFP 행만)."""
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    try:
        raw = json.dumps(body, ensure_ascii=False)
        norm = normalize_reference_code_payload(raw)
    except ValueError:
        return JSONResponse({"ok": False, "error": "too_large"}, status_code=400)
    rfp.reference_code_payload = norm
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/rfp/{rfp_id}/reference-codes")
def delete_rfp_reference_codes(
    rfp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    rfp = db.query(models.RFP).filter(
        models.RFP.id == rfp_id, models.RFP.user_id == user.id
    ).first()
    if not rfp:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    rfp.reference_code_payload = None
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_legacy_redirect(request: Request):
    """레거시 URL — 홈으로 리다이렉트(진행 건수는 홈 타일)."""
    return RedirectResponse(url="/", status_code=302)
