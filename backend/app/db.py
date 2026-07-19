from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import BACKEND_ROOT, get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


@event.listens_for(engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    del connection_record
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        if settings.database_url != "sqlite://":
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if alembic_ini.exists():
        alembic_config = Config(str(alembic_ini))
        alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
        alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        command.upgrade(alembic_config, "head")
    else:
        SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
