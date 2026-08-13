import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_path() -> Path:
    configured = os.getenv("CONTROL_PLANE_DATABASE_PATH")
    if configured:
        return Path(configured).expanduser()
    data_root = os.getenv("CONTROL_PLANE_DATA_ROOT")
    if data_root:
        return Path(data_root).expanduser() / "control-plane.db"
    return Path(__file__).resolve().parents[2] / "data" / "control-plane.db"


def database_url() -> str:
    configured = os.getenv("CONTROL_PLANE_DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{database_path().resolve().as_posix()}"


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def configure_database(url: str | None = None) -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    target_url = url or database_url()
    if _is_sqlite(target_url):
        sqlite_url = make_url(target_url)
        if sqlite_url.database and sqlite_url.database != ":memory:":
            Path(sqlite_url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        engine_options = {"connect_args": {"timeout": 5}, "pool_pre_ping": True}
        if sqlite_url.database != ":memory:":
            engine_options.update(pool_size=5, max_overflow=0)
        _engine = create_engine(target_url, **engine_options)
        event.listen(_engine, "connect", _configure_sqlite_connection)
    else:
        _engine = create_engine(target_url, pool_pre_ping=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine() -> Engine:
    if _engine is None:
        configure_database()
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    global _session_factory
    if _session_factory is None:
        configure_database()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_schema() -> dict:
    from backend.control_plane.models import CONTROL_PLANE_TABLES

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            existing = set(inspect(connection).get_table_names())
    except Exception as exc:
        return {"database": False, "schema": False, "missing_tables": list(CONTROL_PLANE_TABLES), "error": type(exc).__name__}
    missing_tables = sorted(CONTROL_PLANE_TABLES - existing)
    return {"database": True, "schema": not missing_tables, "missing_tables": missing_tables}
