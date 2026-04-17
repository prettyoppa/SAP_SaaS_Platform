import os
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


def _ensure_postgres_sslmode(url: str) -> str:
    """Railway 공개 프록시(rlwy.net) 등은 SSL이 필요한 경우가 많음. 내부 호스트는 건드리지 않음."""
    if not url.startswith("postgresql"):
        return url
    if "sslmode=" in url:
        return url
    lower = url.lower()
    # *.railway.internal — 컨테이너 간 통신, 보통 sslmode 불필요
    if ".railway.internal" in lower:
        return url
    # Railway 외부 접속용 프록시 호스트
    if ".rlwy.net" in lower or "proxy.rlwy.net" in lower:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}sslmode=require"
    return url


def _resolve_database_url() -> str:
    """Railway 등 PaaS에서는 cwd가 달라질 수 있어 SQLite 경로를 명시합니다.

    Railway Postgres의 DATABASE_URL은 종종 host=postgres.railway.internal 인데,
    웹 서비스가 사설 DNS에 붙지 않으면 "could not translate host name" 이 납니다.
    그럴 때는 Postgres의 공개 접속 URL을 DATABASE_PUBLIC_URL 로 넣으세요(웹 서비스 Variables).
    """
    # 공개 프록시(*.rlwy.net 등)가 있으면 internal DNS 문제를 피할 수 있음
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if url:
        url = url.strip().strip('"').strip("'")
        # Railway/Heroku style postgres:// → SQLAlchemy postgresql://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return _ensure_postgres_sslmode(url)
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
        return "sqlite:////tmp/saas_platform.db"
    return "sqlite:///./saas_platform.db"


DATABASE_URL = _resolve_database_url()


def _postgres_connect_args() -> dict:
    return {"connect_timeout": 20}


def db_target_log_line() -> str:
    """비밀번호 없이 연결 대상만 로그용으로 반환합니다."""
    if DATABASE_URL.startswith("sqlite"):
        return f"database=sqlite path={DATABASE_URL}"
    try:
        p = urlparse(DATABASE_URL)
        host = p.hostname or "?"
        port = f":{p.port}" if p.port else ""
        db = (p.path or "/").lstrip("/") or "?"
        return f"database=postgresql host={host}{port} dbname={db}"
    except Exception:
        return "database=postgresql (parse error)"


if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args=_postgres_connect_args(),
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
