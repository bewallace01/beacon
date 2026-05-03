"""Database engine + session management.

Postgres-only since Phase 4.1. Connection URL comes from LIGHTSEI_DATABASE_URL.
"""
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

_RAW_DATABASE_URL = os.environ.get(
    "LIGHTSEI_DATABASE_URL",
    "postgresql+psycopg://lightsei:lightsei@localhost:5432/lightsei",
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

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    # SQLAlchemy's default pool is 5 + 10 overflow = 15 connections.
    # Combined with the dispatch + dashboard polling traffic post
    # Phase 11, that gets saturated when even a small number of
    # request-cancelled sessions leak (the 30s server-side
    # idle_in_transaction_session_timeout cleans them up but the
    # window is wide enough that bursts stack up). Tripling the
    # pool gives breathing room until the leak source is patched.
    pool_size=20,
    max_overflow=40,
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


@event.listens_for(engine, "connect")
def _set_pg_session_defaults(dbapi_connection, _connection_record) -> None:
    """Server-side safety net for txn leaks.

    On every new pool connection, set idle_in_transaction_session_timeout to
    30s. If FastAPI's dep cleanup doesn't fire (Starlette doesn't always run
    generator-based dep finalizers when the client disconnects mid-request),
    Postgres will roll back the orphaned txn after 30s instead of letting it
    sit forever and saturate the pool. After the timeout the connection is
    closed; the pool reopens it with these settings re-applied via this
    listener.

    Belt-and-suspenders alongside the defensive rollback in get_session() —
    this catches cases where the dep finalizer runs but never reaches the
    rollback (e.g. an exception inside the rollback itself), and protects
    against any future session-acquiring path we forget to wrap.
    """
    cur = dbapi_connection.cursor()
    try:
        cur.execute("SET idle_in_transaction_session_timeout = '30s'")
    finally:
        cur.close()


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
    """FastAPI dependency.

    Inlined try/yield/commit/rollback/close instead of `with session_scope()`
    so the cleanup runs cleanly when Starlette cancels the request mid-flight.
    Generator-based deps wrapped in another contextmanager have an extra layer
    of suspended frames that don't always unwind on GeneratorExit, which is
    the path we hit when the client disconnects (page nav, browser refresh,
    parallel-fetch race) — exactly the pattern that filled the prod pool with
    "idle in transaction" zombies during the Phase 10.6 demo.
    """
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        # Defensive: if the dep was cancelled and neither commit nor rollback
        # fired, this resets the txn so the connection returns to the pool
        # clean. After commit/rollback this is a no-op.
        try:
            s.rollback()
        except Exception:
            pass
        s.close()


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
