"""요청(RFP·연동·분석) 산출물: 복사·다운로드는 소유자 또는 매칭 컨설턴트만.

코드 라이브러리(ABAPCode)는 관리자 전용 메뉴·라우트에서 별도 권한으로 처리한다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


def consultant_is_matched_on_request(
    db: Session, *, consultant_user_id: int, request_kind: str, request_id: int
) -> bool:
    return (
        db.query(models.RequestOffer.id)
        .filter(
            models.RequestOffer.consultant_user_id == consultant_user_id,
            models.RequestOffer.request_kind == request_kind,
            models.RequestOffer.request_id == request_id,
            models.RequestOffer.status == "matched",
        )
        .first()
        is not None
    )


def user_may_copy_download_request_assets(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
) -> bool:
    if not user:
        return False
    if int(user.id) == int(owner_user_id):
        return True
    return consultant_is_matched_on_request(
        db,
        consultant_user_id=int(user.id),
        request_kind=request_kind,
        request_id=int(request_id),
    )


def user_may_download_fs_markdown(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
) -> bool:
    """FS .md 다운로드: 매칭 컨설턴트·관리자만 (요청자/소유자는 PDF만)."""
    if not user:
        return False
    if getattr(user, "is_admin", False):
        return True
    if getattr(user, "is_consultant", False):
        return consultant_is_matched_on_request(
            db,
            consultant_user_id=int(user.id),
            request_kind=request_kind,
            request_id=int(request_id),
        )
    return False


def fs_download_ui_flags(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    fs_status: str | None,
    fs_text: str | None,
    code_asset_unlocked: bool,
) -> dict[str, bool]:
    """허브 FS 다운로드 버튼 노출 (PDF=요청자·컨설턴트, MD=컨설턴트·관리자)."""
    del owner_user_id
    fs_ready = (fs_status or "").strip() == "ready" and bool((fs_text or "").strip())
    base = bool(code_asset_unlocked and fs_ready)
    return {
        "fs_download_allow_pdf": base,
        "fs_download_allow_md": base
        and user_may_download_fs_markdown(
            db, user, request_kind=request_kind, request_id=int(request_id)
        ),
    }


def fs_download_hub_ctx(
    db: Session,
    user,
    *,
    request_kind: str,
    request_id: int,
    owner_user_id: int,
    fs_status: str | None,
    fs_text: str | None,
    code_asset_unlocked: bool,
    download_base: str,
) -> dict[str, bool | str]:
    flags = fs_download_ui_flags(
        db,
        user,
        request_kind=request_kind,
        request_id=int(request_id),
        owner_user_id=int(owner_user_id),
        fs_status=fs_status,
        fs_text=fs_text,
        code_asset_unlocked=code_asset_unlocked,
    )
    return {**flags, "fs_download_base": download_base}
