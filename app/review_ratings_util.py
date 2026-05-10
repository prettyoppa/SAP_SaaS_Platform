"""문의/리뷰 글에 대한 회원 평점(작성자 본인 제외) 집계."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


def review_author_label(review: models.Review) -> str:
    """표시 이름: 비어 있으면 익명."""
    raw = (getattr(review, "display_name", None) or "").strip()
    return raw if raw else "익명"


def rating_aggregates_for_reviews(db: Session, review_ids: list[int]) -> dict[int, dict]:
    """review_id -> {avg: float|None, count: int}"""
    if not review_ids:
        return {}
    rows = (
        db.query(
            models.ReviewRating.review_id,
            func.avg(models.ReviewRating.stars).label("avg_s"),
            func.count(models.ReviewRating.id).label("cnt"),
        )
        .filter(models.ReviewRating.review_id.in_(review_ids))
        .group_by(models.ReviewRating.review_id)
        .all()
    )
    out: dict[int, dict] = {}
    for rid, avg_s, cnt in rows:
        out[int(rid)] = {
            "avg": float(avg_s) if avg_s is not None else None,
            "count": int(cnt or 0),
        }
    return out


def user_ratings_for_reviews(db: Session, review_ids: list[int], user_id: int) -> dict[int, int]:
    """현재 사용자가 매긴 별점 review_id -> stars"""
    if not review_ids or not user_id:
        return {}
    rows = (
        db.query(models.ReviewRating.review_id, models.ReviewRating.stars)
        .filter(
            models.ReviewRating.review_id.in_(review_ids),
            models.ReviewRating.user_id == user_id,
        )
        .all()
    )
    return {int(rid): int(stars) for rid, stars in rows}


def single_review_rating_context(db: Session, review: models.Review, user: models.User | None):
    """상세·목록용: avg, count, my_stars, can_rate."""
    rid = int(review.id)
    agg = rating_aggregates_for_reviews(db, [rid]).get(rid, {"avg": None, "count": 0})
    my_stars = None
    uid = int(user.id) if user else 0
    if uid:
        m = user_ratings_for_reviews(db, [rid], uid)
        my_stars = m.get(rid)
    ru = getattr(review, "user_id", None)
    is_author = bool(user and ru is not None and int(ru) == uid)
    can_rate = bool(user and not is_author)
    return {
        "avg": agg["avg"],
        "count": agg["count"],
        "my_stars": my_stars,
        "can_rate": can_rate,
    }
