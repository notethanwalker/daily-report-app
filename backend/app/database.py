import os
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str:
    direct = os.getenv("DATABASE_URL")
    if direct:
        return direct

    password = os.getenv("AIVEN_DB_PASSWORD")
    if not password:
        raise RuntimeError("DATABASE_URL or AIVEN_DB_PASSWORD is required")

    user = os.getenv("AIVEN_DB_USER", "avnadmin")
    host = os.environ["AIVEN_DB_HOST"]
    port = os.getenv("AIVEN_DB_PORT", "28265")
    database = os.getenv("AIVEN_DB_NAME", "defaultdb")
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{database}?sslmode=require"
    )


DATABASE_URL = _database_url()

# Explicitly tell SQLAlchemy to use psycopg v3.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )

# PostgreSQL production runs several cache/refresh workers in the same process as
# interactive requests. SQLAlchemy's default QueuePool (5 + 10 overflow) can be
# exhausted when maintenance overlaps a UI burst. Keep a bounded reserve for user
# traffic, fail faster than the proxy ceiling, and recycle older idle connections.
# Tests use SQLite, whose SingletonThreadPool does not accept QueuePool-only options.
engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("postgresql+"):
    engine_kwargs.update(
        pool_size=int(os.getenv("DB_POOL_SIZE", "8")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "12")),
        pool_timeout=float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "8")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300")),
        pool_use_lifo=True,
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
