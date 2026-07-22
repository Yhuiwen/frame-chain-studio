from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.config import BACKEND_ROOT, PRODUCTION_DATABASE_PATH, Settings, normalize_sqlite_url, resolve_backend_path
from app.main import create_app


def test_relative_paths_resolve_from_backend_root() -> None:
    settings = Settings(
        database_url="sqlite:///./data/example.db",
        storage_root=None,
        storage_dir=Path("./data/storage"),
        fixture_dir=Path("./tests/fixtures"),
        provider_config_file=Path("provider-config.example.json"),
    )

    assert settings.database_url == f"sqlite:///{(BACKEND_ROOT / 'data/example.db').resolve().as_posix()}"
    assert settings.storage_dir == (BACKEND_ROOT / "data/storage").resolve()
    assert settings.fixture_dir == (BACKEND_ROOT / "tests/fixtures").resolve()
    assert settings.provider_config_file == (BACKEND_ROOT / "provider-config.example.json").resolve()
    assert normalize_sqlite_url("sqlite://") == "sqlite://"
    assert resolve_backend_path("provider-config.example.json") == (BACKEND_ROOT / "provider-config.example.json").resolve()


def test_test_environment_rejects_production_database() -> None:
    with pytest.raises(ValueError, match="TEST_DATABASE_POINTS_TO_PRODUCTION"):
        Settings(env="test", database_url=f"sqlite:///{PRODUCTION_DATABASE_PATH.as_posix()}")


def test_development_environment_keeps_default_database_support() -> None:
    settings = Settings(env="development", database_url=f"sqlite:///{PRODUCTION_DATABASE_PATH.as_posix()}")
    assert settings.database_url == f"sqlite:///{PRODUCTION_DATABASE_PATH.as_posix()}"


def test_ready_response_is_safe() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/ready")

    assert response.status_code == 200
    payload = response.json()
    assert "checks" in payload
    assert "config" in payload
    text = str(payload)
    assert str(Path.home()) not in text
    assert "api_key" not in text.lower()


def test_request_id_header_and_error_payload() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/projects/999999", headers={"X-Request-ID": "../not safe" * 20})

    assert response.status_code == 404
    request_id = response.headers["X-Request-ID"]
    assert request_id
    assert request_id != "../not safe" * 20
    assert response.json()["error"]["request_id"] == request_id
