import os
from urllib.parse import quote, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


def _is_postgres_scheme(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith("postgresql://") or u.startswith("postgres://")


def _normalize_postgres_scheme(url: str) -> str:
    url = url.strip().strip('"').strip("'")
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _split_host_port(spec: str) -> tuple[str, str | None]:
    """'host' 또는 'host:port' 분리 (Railway 공개 엔드포인트용)."""
    if ":" in spec:
        idx = spec.rfind(":")
        if idx > 0 and spec[idx + 1 :].isdigit():
            return spec[:idx], spec[idx + 1 :]
    return spec, None


def _merge_public_endpoint(private_url: str, public_spec: str) -> str:
    """DATABASE_PUBLIC_URL 이 host:port 만 있을 때 private DATABASE_URL 과 병합."""
    private_url = _normalize_postgres_scheme(private_url)
    if not private_url.startswith("postgresql"):
        raise ValueError(
            "DATABASE_PUBLIC_URL 이 host:port 형태일 때는 유효한 DATABASE_URL(비밀번호·DB명 포함)이 "
            "같이 있어야 합니다. Postgres Variables에서 DATABASE_URL 전체를 web에도 넣으세요."
        )
    p = urlparse(private_url)
    new_host, port_str = _split_host_port(public_spec.strip())
    if not new_host:
        raise ValueError("DATABASE_PUBLIC_URL 의 호스트가 비어 있습니다.")
    new_port = int(port_str) if port_str else (p.port or 5432)

    user, password = p.username or "", p.password or ""
    if user:
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}@" if password else f"{quote(user, safe='')}@"
    else:
        auth = ""

    netloc = f"{auth}{new_host}:{new_port}"
    path = p.path if p.path else "/railway"
    return urlunparse(("postgresql", netloc, path, "", p.query, p.fragment))


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

    DATABASE_PUBLIC_URL 에는 아래 둘 중 하나를 넣을 수 있습니다.
    - 전체 postgresql://user:pass@host:port/dbname
    - 또는 host:port 만 (이 경우 웹 서비스에 DATABASE_URL 전체가 같이 있어야 병합됨)
    """
    private = os.environ.get("DATABASE_URL")
    public_raw = os.environ.get("DATABASE_PUBLIC_URL")
    url: str | None = None

    if public_raw:
        public_raw = public_raw.strip().strip('"').strip("'")
        if _is_postgres_scheme(public_raw):
            url = _normalize_postgres_scheme(public_raw)
        elif private:
            url = _merge_public_endpoint(private, public_raw)
        else:
            raise ValueError(
                "DATABASE_PUBLIC_URL 이 host:port 만 있습니다. "
                "웹 서비스에 Postgres의 DATABASE_URL 전체를 함께 설정하거나, "
                "DATABASE_PUBLIC_URL 에 postgresql:// 전체 URL을 넣으세요."
            )
    elif private:
        url = _normalize_postgres_scheme(private)

    if url:
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
