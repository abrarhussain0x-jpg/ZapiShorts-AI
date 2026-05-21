"""Production-grade database engine with connection pooling and session management."""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from src.config.settings import settings
from src.database.models import Base

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────
_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {
    "echo": settings.database_echo,
}

if _is_sqlite:
    # SQLite-specific: disable connection-pool (each call opens its own file fd),
    # allow usage across threads, and enable WAL mode for concurrent reads.
    _engine_kwargs.update(
        {
            "poolclass": NullPool,
            "connect_args": {"check_same_thread": False},
        }
    )
else:
    # PostgreSQL / MySQL: full connection pool from settings.
    _engine_kwargs.update(
        {
            "poolclass": QueuePool,
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout,
            "pool_recycle": settings.database_pool_recycle,
            "pool_pre_ping": True,  # detect stale connections
        }
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

# Enable WAL mode for SQLite (dramatically improves concurrent access).
if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # keep objects usable after commit
)


# ── Public helpers ────────────────────────────────────────────────────────────
def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised — all tables ready.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a scoped DB session, always closed on exit."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for use outside FastAPI request scope (background tasks, CLI)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_connection() -> bool:
    """Health check — returns True if DB is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
