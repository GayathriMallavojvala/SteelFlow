import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.engine import Engine

DEFAULT_URL = "sqlite:///./steelflow-dev.db"

class Base(DeclarativeBase):
    pass

def new_engine(url: str | None = None) -> Engine:
    url = url or os.getenv("DATABASE_URL", DEFAULT_URL)
    kw = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False, "timeout": 20}
    engine = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_settings(conn, _):
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=20000")
            cursor.close()
    return engine

def make_session_factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
