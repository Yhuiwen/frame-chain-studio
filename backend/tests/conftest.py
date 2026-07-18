from collections.abc import Generator
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings


@pytest.fixture()
def session(tmp_path: Path) -> Generator[Session, None, None]:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.fixture_dir = tmp_path / "fixtures"
    settings.mock_task_delay_seconds = 0
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
