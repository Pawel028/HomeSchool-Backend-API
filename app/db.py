"""Database engine, session handling and Row-Level Security context.

Every request runs in ONE transaction. The request's identity is written into transaction-local settings
(app.user_id for parents, app.family_id for child tokens) each time a transaction begins, and the RLS policies
in migrations/versions/0001_initial.py read them. Application-level authorization still runs first; RLS is the
second line of defence (ADR-016).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_engine(
            s.sqlalchemy_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    return _engine


def get_factory() -> sessionmaker[Session]:
    global _factory
    if _factory is None:
        _factory = sessionmaker(bind=get_engine(), autoflush=True, expire_on_commit=False)
    return _factory


def dispose_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def apply_rls_context(session: Session) -> None:
    """Write the session's identity into the current transaction (transaction-local)."""
    user_id = session.info.get("rls_user_id")
    family_id = session.info.get("rls_family_id")
    conn = session.connection()
    conn.execute(text("select set_config('app.user_id', :v, true)"), {"v": str(user_id) if user_id else ""})
    conn.execute(text("select set_config('app.family_id', :v, true)"), {"v": str(family_id) if family_id else ""})


@event.listens_for(Session, "after_begin")
def _on_begin(session: Session, transaction, connection) -> None:  # noqa: ANN001
    if "rls_user_id" in session.info or "rls_family_id" in session.info:
        connection.execute(
            text("select set_config('app.user_id', :u, true), set_config('app.family_id', :f, true)"),
            {"u": str(session.info.get("rls_user_id") or ""), "f": str(session.info.get("rls_family_id") or "")},
        )


def set_rls_identity(session: Session, *, user_id=None, family_id=None) -> None:
    session.info["rls_user_id"] = user_id
    session.info["rls_family_id"] = family_id
    apply_rls_context(session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session and one transaction per request, committed on success."""
    session = get_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
