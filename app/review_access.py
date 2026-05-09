"""문의/리뷰(Review) 열람·삭제 권한."""

from __future__ import annotations

from . import models


def review_visible_in_public_feed(review: models.Review) -> bool:
    """목록·홈·비로그인 단건 열람에 노출되는 공개 글."""
    return bool(review.is_public) and not bool(getattr(review, "admin_suppressed", False))


def can_view_review(review: models.Review, user: models.User | None) -> bool:
    if review_visible_in_public_feed(review):
        return True
    if not user:
        return False
    if getattr(user, "is_admin", False):
        return True
    return int(review.user_id) == int(user.id)


def can_delete_review(review: models.Review, user: models.User | None) -> bool:
    if not user:
        return False
    if getattr(user, "is_admin", False):
        return True
    return int(review.user_id) == int(user.id)
