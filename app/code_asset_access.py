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
