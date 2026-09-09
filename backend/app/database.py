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

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

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
