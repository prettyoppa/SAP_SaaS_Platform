from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from .. import models, auth
from ..database import get_db
from ..review_access import can_delete_review, can_view_review
from ..review_ratings_util import (
    rating_aggregates_for_reviews,
    user_ratings_for_reviews,
    single_review_rating_context,
)
from ..templates_config import templates

router = APIRouter(prefix="/reviews")


@router.get("", response_class=HTMLResponse)
def reviews_board(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/reviews", status_code=302)
    visible = or_(
        and_(models.Review.is_public == True, models.Review.admin_suppressed == False),
        models.Review.user_id == user.id,
    )
    board_reviews = (
        db.query(models.Review)
        .options(
            joinedload(models.Review.author),
            joinedload(models.Review.comments).joinedload(models.ReviewComment.author),
        )
        .filter(visible)
        .order_by(models.Review.created_at.desc())
        .all()
    )
    rids = [r.id for r in board_reviews]
    rating_meta = rating_aggregates_for_reviews(db, rids)
    my_ratings = user_ratings_for_reviews(db, rids, int(user.id))
    return templates.TemplateResponse(
        request,
        "reviews/board.html",
        {
            "request": request,
            "user": user,
            "board_reviews": board_reviews,
            "rating_meta": rating_meta,
            "my_ratings": my_ratings,
        },
    )


@router.get("/{review_id}", response_class=HTMLResponse)
def review_detail(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    r = (
        db.query(models.Review)
        .options(
            joinedload(models.Review.author),
            joinedload(models.Review.comments).joinedload(models.ReviewComment.author),
        )
        .filter(models.Review.id == review_id)
        .first()
    )
    if not r or not can_view_review(r, user):
        return templates.TemplateResponse(
            request,
            "errors/simple_message.html",
            {
                "request": request,
                "user": user,
                "title": "문의/리뷰",
                "message": "존재하지 않거나 열람 권한이 없는 글입니다.",
            },
            status_code=404,
        )
    comments = sorted(list(r.comments or []), key=lambda c: (c.created_at or 0, c.id))
    rating_ctx = single_review_rating_context(db, r, user)
    return templates.TemplateResponse(
        request,
        "reviews/detail.html",
        {
            "request": request,
            "user": user,
            "review": r,
            "comments": comments,
            "can_delete": can_delete_review(r, user),
            "rating_ctx": rating_ctx,
        },
    )


@router.post("/write")
def write_review(
    request: Request,
    content: str = Form(...),
    display_name: str = Form(""),
    is_private: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    is_public = (is_private or "").strip() not in ("1", "on", "true", "yes")
    dn = (display_name or "").strip()
    review = models.Review(
        user_id=user.id,
        content=(content or "").strip(),
        rating=0,
        display_name=dn if dn else None,
        is_public=is_public,
        admin_suppressed=False,
    )
    db.add(review)
    db.commit()
    return RedirectResponse(url="/reviews?submitted=1", status_code=303)


@router.post("/{review_id}/rate")
def rate_review(
    review_id: int,
    request: Request,
    stars: int = Form(5),
    next: str = Form("/reviews"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/reviews", status_code=302)
    stars = max(1, min(5, int(stars)))
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review or not can_view_review(review, user):
        return RedirectResponse(url="/reviews", status_code=303)
    if review.user_id is not None and int(review.user_id) == int(user.id):
        nxt = (next or "").strip()
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/reviews"
        return RedirectResponse(url=nxt, status_code=303)
    row = (
        db.query(models.ReviewRating)
        .filter(
            models.ReviewRating.review_id == review_id,
            models.ReviewRating.user_id == user.id,
        )
        .first()
    )
    if row:
        row.stars = stars
    else:
        db.add(
            models.ReviewRating(
                review_id=review_id,
                user_id=user.id,
                stars=stars,
            )
        )
    db.commit()
    nxt = (next or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = f"/reviews/{review_id}"
    return RedirectResponse(url=nxt, status_code=303)


@router.post("/{review_id}/delete")
def delete_review(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if review and can_delete_review(review, user):
        db.delete(review)
        db.commit()
    return RedirectResponse(url="/reviews", status_code=303)


@router.post("/{review_id}/comment")
def add_comment(
    review_id: int,
    request: Request,
    content: str = Form(...),
    next: str = Form("/reviews"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    review = (
        db.query(models.Review)
        .filter(models.Review.id == review_id)
        .first()
    )
    if review and can_view_review(review, user):
        comment = models.ReviewComment(review_id=review_id, user_id=user.id, content=(content or "").strip())
        db.add(comment)
        db.commit()
    nxt = (next or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = f"/reviews/{review_id}"
    return RedirectResponse(url=nxt, status_code=303)
