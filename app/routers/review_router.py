from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db
from ..templates_config import templates

router = APIRouter(prefix="/reviews")


@router.get("", response_class=HTMLResponse)
def reviews_page(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    my_reviews = (db.query(models.Review)
                  .filter(models.Review.user_id == user.id)
                  .order_by(models.Review.created_at.desc())
                  .all())
    return templates.TemplateResponse("reviews.html", {
        "request": request, "user": user, "my_reviews": my_reviews,
    })


@router.post("/write")
def write_review(
    request: Request,
    content: str = Form(...),
    rating: int = Form(5),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rating = max(1, min(5, rating))
    review = models.Review(user_id=user.id, content=content.strip(), rating=rating)
    db.add(review)
    db.commit()
    return RedirectResponse(url="/reviews?submitted=1", status_code=302)


@router.post("/{review_id}/delete")
def delete_review(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    review = db.query(models.Review).filter(
        models.Review.id == review_id, models.Review.user_id == user.id
    ).first()
    if review:
        db.delete(review)
        db.commit()
    return RedirectResponse(url="/reviews", status_code=302)


@router.post("/{review_id}/comment")
def add_comment(
    review_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    review = db.query(models.Review).filter(
        models.Review.id == review_id, models.Review.is_public == True
    ).first()
    if review:
        comment = models.ReviewComment(review_id=review_id, user_id=user.id, content=content.strip())
        db.add(comment)
        db.commit()
    return RedirectResponse(url="/#tab-reviews", status_code=302)
