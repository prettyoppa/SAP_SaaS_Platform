"""FS Markdown/PDF 다운로드 HTTP 응답 (RFP·연동·분석개선 공통)."""

from __future__ import annotations

from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from .agent_display import prepare_member_facing_proposal_markdown
from .code_asset_access import user_may_copy_download_request_assets, user_may_download_fs_markdown
from .proposal_export import (
    ProposalPdfGenerationFailed,
    ProposalPdfUnavailable,
    proposal_pdf_download_body,
    proposal_pdf_error_http_response,
)
from .rfp_download_names import (
    content_disposition_attachment,
    fs_md_download_basename,
    fs_pdf_download_basename,
)


def normalize_fs_download_format(format_param: str) -> str:
    fmt = (format_param or "pdf").strip().lower()
    return fmt if fmt in ("md", "pdf") else "pdf"


def fs_download_http_response(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    fs_status: str | None,
    fs_text: str | None,
    program_id: str | None,
    title: str | None,
    format_param: str,
    not_ready_redirect_url: str,
    md_denied_redirect_url: str,
) -> Response | RedirectResponse:
    if not user_may_copy_download_request_assets(
        db,
        user,
        request_kind=request_kind,
        request_id=int(request_id),
        owner_user_id=int(owner_user_id),
    ):
        return RedirectResponse(url="/", status_code=302)
    if (fs_status or "").strip() != "ready" or not (fs_text or "").strip():
        return RedirectResponse(url=not_ready_redirect_url, status_code=302)

    fmt = normalize_fs_download_format(format_param)
    if fmt == "md" and not user_may_download_fs_markdown(
        db, user, request_kind=request_kind, request_id=int(request_id)
    ):
        return RedirectResponse(url=md_denied_redirect_url, status_code=302)

    pid = program_id
    tit = title
    if fmt == "md":
        body = (fs_text or "").encode("utf-8")
        fname = fs_md_download_basename(pid, tit)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": content_disposition_attachment(fname)},
        )

    fs_md = prepare_member_facing_proposal_markdown(fs_text or "")
    try:
        pdf_body = proposal_pdf_download_body(
            fs_md, document_title=(title or "Functional Specification")
        )
    except ProposalPdfUnavailable:
        return proposal_pdf_error_http_response(reason="unavailable")
    except ProposalPdfGenerationFailed:
        return proposal_pdf_error_http_response(reason="generation")
    fname = fs_pdf_download_basename(pid, tit)
    return Response(
        content=pdf_body,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )
