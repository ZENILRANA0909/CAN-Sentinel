"""Database engine, session management and schema bootstrap.

CAN-Sentinel uses synchronous SQLAlchemy deliberately.  The alternative - an
async driver - buys nothing here because SQLite serialises writes anyway, and
it would make the batching writer considerably harder to reason about.  Every
database call from async code is instead pushed onto a worker thread with
``asyncio.to_thread`` so the event loop is never blocked.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.models.base import Base

logger = get_logger("storage.database")


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory(url: str) -> bool:
    return ":memory:" in url or "mode=memory" in url


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, url: str, *, echo: bool = False, sqlite_path: Path | None = None) -> None:
        self.url = url
        self.echo = echo
        self.sqlite_path = sqlite_path
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        # A StaticPool hands every thread the *same* DBAPI connection, and
        # sqlite3 raises "bad parameter or other API misuse" if two threads use
        # one connection concurrently. Sessions are opened from worker threads
        # (the batching writer, and every API query), so access has to be
        # serialised in that configuration. A QueuePool gives each thread its
        # own connection and needs no lock.
        self._serialize_access = False
        self._access_lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Create the engine, applying SQLite tuning where applicable."""
        if self._engine is not None:
            return

        kwargs: dict[str, Any] = {"echo": self.echo, "future": True, "pool_pre_ping": True}
        if _is_sqlite(self.url):
            # Sessions are used from worker threads, so the default
            # same-thread guard has to be relaxed.
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if _is_memory(self.url):
                # A single shared connection, otherwise every thread would get
                # its own empty in-memory database.
                kwargs["poolclass"] = StaticPool
                self._serialize_access = True
            elif self.sqlite_path is not None:
                self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            engine = create_engine(self.url, **kwargs)
        except SQLAlchemyError as exc:
            raise StorageError(f"could not create database engine: {exc}") from exc

        if _is_sqlite(self.url):
            _install_sqlite_pragmas(engine)

        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        logger.info("Database engine created", extra={"context": {"url": self._safe_url()}})

    def init_schema(self) -> None:
        """Create any missing tables.

        Alembic owns migrations for a real deployment; this keeps a fresh
        checkout and the test-suite working without a migration step.
        """
        self.connect()
        assert self._engine is not None
        try:
            Base.metadata.create_all(self._engine)
        except SQLAlchemyError as exc:
            raise StorageError(f"could not initialise database schema: {exc}") from exc
        logger.info("Database schema ready")

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            logger.info("Database engine disposed")
        self._engine = None
        self._session_factory = None

    # ------------------------------------------------------------------ #
    # Access                                                             #
    # ------------------------------------------------------------------ #
    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise StorageError("database is not connected")
        return self._engine

    @property
    def is_connected(self) -> bool:
        return self._engine is not None

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional session scope; commits on success, rolls back on error."""
        if self._session_factory is None:
            raise StorageError("database is not connected")
        if self._serialize_access:
            self._access_lock.acquire()
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"database operation failed: {exc}") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if self._serialize_access:
                self._access_lock.release()

    # ------------------------------------------------------------------ #
    # Health                                                             #
    # ------------------------------------------------------------------ #
    def healthcheck(self) -> dict[str, Any]:
        """Cheap liveness probe used by ``/api/health``."""
        if self._engine is None:
            return {"connected": False, "healthy": False, "error": "not connected"}
        try:
            # Takes the same lock as session(): on a shared connection this
            # probe must not run concurrently with a writer commit.
            if self._serialize_access:
                self._access_lock.acquire()
            try:
                with self._engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            finally:
                if self._serialize_access:
                    self._access_lock.release()
        except SQLAlchemyError as exc:
            logger.error("Database healthcheck failed", extra={"context": {"error": str(exc)}})
            return {"connected": True, "healthy": False, "error": str(exc)}
        payload: dict[str, Any] = {"connected": True, "healthy": True, "url": self._safe_url()}
        if self.sqlite_path is not None and self.sqlite_path.exists():
            payload["size_bytes"] = self.sqlite_path.stat().st_size
            payload["path"] = str(self.sqlite_path)
        return payload

    def _safe_url(self) -> str:
        """Never leak credentials that may appear in a non-SQLite URL."""
        if "@" not in self.url:
            return self.url
        scheme, _, rest = self.url.partition("://")
        _, _, host = rest.partition("@")
        return f"{scheme}://***@{host}"


def _install_sqlite_pragmas(engine: Engine) -> None:
    """WAL journaling lets the writer commit while readers query."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()
