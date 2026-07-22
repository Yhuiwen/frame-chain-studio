from collections.abc import Generator
import os
from pathlib import Path
import shutil
import tempfile

import pytest
from sqlmodel import Session, SQLModel, create_engine

_TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="frame-chain-pytest-"))
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_DATABASE = (_BACKEND_ROOT / "data" / "frame_chain.db").resolve()
_requested_environment = os.environ.get("FCS_ENV", "").lower()
_requested_database = os.environ.get("FCS_DATABASE_URL", "")
if _requested_environment == "test" and _requested_database.startswith("sqlite:///"):
    _raw_database = _requested_database.removeprefix("sqlite:///")
    _requested_path = Path(_raw_database)
    _resolved_database = (
        _requested_path.resolve()
        if _requested_path.is_absolute()
        else (_BACKEND_ROOT / _requested_path).resolve()
    )
    if _resolved_database == _PRODUCTION_DATABASE:
        raise RuntimeError("TEST_DATABASE_POINTS_TO_PRODUCTION")

os.environ["FCS_ENV"] = "test"
if _requested_environment != "test" or not _requested_database:
    os.environ["FCS_DATABASE_URL"] = f"sqlite:///{(_TEST_RUNTIME / 'test.db').as_posix()}"
os.environ["FCS_STORAGE_DIR"] = str(_TEST_RUNTIME / "storage")
os.environ["FCS_STORAGE_ROOT"] = str(_TEST_RUNTIME / "storage")
os.environ["FCS_LOG_DIR"] = str(_TEST_RUNTIME / "logs")

from app.core.config import get_settings  # noqa: E402


def pytest_sessionfinish() -> None:
    shutil.rmtree(_TEST_RUNTIME, ignore_errors=True)


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
