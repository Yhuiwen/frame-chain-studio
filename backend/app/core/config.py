from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Frame Chain Studio API"
    database_url: str = "sqlite:///./data/frame_chain.db"
    storage_dir: Path = Path("./data/storage")
    fixture_dir: Path = Path("./tests/fixtures")
    mock_task_delay_seconds: float = 0.05
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FCS_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
