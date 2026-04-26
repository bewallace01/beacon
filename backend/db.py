"""Database engine + session management.

Postgres-only since Phase 4.1. Connection URL comes from BEACON_DATABASE_URL.
"""
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_RAW_DATABASE_URL = os.environ.get(
    "BEACON_DATABASE_URL",
    "postgresql+psycopg://beacon:beacon@localhost:5432/beacon",
)


def _normalize_database_url(url: str) -> str:
    """Make sure SQLAlchemy uses psycopg 3 (the driver we ship in requirements).

    Some hosts (Railway, Heroku) expose the URL as `postgresql://...`, which
    SQLAlchemy maps to psycopg 2 by default. We don't ship psycopg 2, so
    rewrite the scheme.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_database_url(_RAW_DATABASE_URL)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as s:
        yield s


def ensure_agent(
    session: Session, workspace_id: str, name: str, now: datetime
) -> None:
    """Insert agents row for (workspace_id, name) if it doesn't already exist."""
    session.execute(
        text(
            """
            INSERT INTO agents (workspace_id, name, daily_cost_cap_usd, created_at, updated_at)
            VALUES (:wsid, :name, NULL, :now, :now)
            ON CONFLICT (workspace_id, name) DO NOTHING
            """
        ),
        {"wsid": workspace_id, "name": name, "now": now},
    )
