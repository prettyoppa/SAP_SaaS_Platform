from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from .. import models, auth
from ..database import get_db
from ..review_access import can_delete_review, can_view_review
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
    return templates.TemplateResponse(
        request,
        "reviews/board.html",
        {
            "request": request,
            "user": user,
            "board_reviews": board_reviews,
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
    return templates.TemplateResponse(
        request,
        "reviews/detail.html",
        {
            "request": request,
            "user": user,
            "review": r,
            "comments": comments,
            "can_delete": can_delete_review(r, user),
        },
    )


@router.post("/write")
def write_review(
    request: Request,
    content: str = Form(...),
    rating: int = Form(5),
    is_private: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rating = max(1, min(5, int(rating)))
    is_public = (is_private or "").strip() not in ("1", "on", "true", "yes")
    review = models.Review(
        user_id=user.id,
        content=(content or "").strip(),
        rating=rating,
        is_public=is_public,
        admin_suppressed=False,
    )
    db.add(review)
    db.commit()
    return RedirectResponse(url="/reviews?submitted=1", status_code=303)


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
