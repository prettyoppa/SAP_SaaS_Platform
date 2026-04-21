import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from . import models
from .database import get_db

SECRET_KEY = "sap-saas-platform-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
EMAIL_VERIFY_SALT = "email-verify-v1"
EMAIL_VERIFY_MAX_AGE_SEC = 3 * 86400  # 3일


def create_email_verification_token(email: str) -> str:
    s = URLSafeTimedSerializer(SECRET_KEY, salt=EMAIL_VERIFY_SALT)
    return s.dumps({"email": email})


def parse_email_verification_token(token: str, max_age_sec: int = EMAIL_VERIFY_MAX_AGE_SEC) -> Optional[str]:
    s = URLSafeTimedSerializer(SECRET_KEY, salt=EMAIL_VERIFY_SALT)
    try:
        data = s.loads(token, max_age=max_age_sec)
        e = data.get("email")
        return e if isinstance(e, str) else None
    except (BadSignature, SignatureExpired):
        return None


def registration_otp_ttl_minutes() -> int:
    try:
        return max(3, min(60, int(os.environ.get("REGISTRATION_CODE_TTL_MIN") or "10")))
    except ValueError:
        return 10


def generate_registration_otp() -> str:
    return f"{secrets.randbelow(900_000) + 100_000:06d}"


def registration_code_hash(email: str, code: str) -> str:
    e = (email or "").strip().lower()
    c = (code or "").strip()
    return hmac.new(SECRET_KEY.encode("utf-8"), f"{e}:{c}".encode("utf-8"), hashlib.sha256).hexdigest()


def registration_codes_equal(email: str, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(registration_code_hash(email, code), stored_hash)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user_from_token(token: str, db: Session) -> Optional[models.User]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    return db.query(models.User).filter(models.User.email == email).first()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_user_from_token(token, db)


def require_login(request: Request, db: Session = Depends(get_db)) -> models.User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user
