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
    env: str = "development"
    result_allowed_private_hosts: str = ""
    result_worker_lease_seconds: int = 300
    result_connect_timeout_seconds: float = 10
    result_read_timeout_seconds: float = 60
    result_total_timeout_seconds: float = 900
    result_max_image_bytes: int = 50 * 1024 * 1024
    result_max_video_bytes: int = 2 * 1024 * 1024 * 1024
    result_max_image_pixels: int = 80_000_000
    result_download_chunk_bytes: int = 1024 * 1024
    result_max_redirects: int = 3
    result_max_attempts: int = 3
    result_retry_base_seconds: float = 2
    result_retry_max_seconds: float = 300
    result_retry_jitter_ratio: float = 0.2
    result_temp_file_ttl_hours: int = 24
    ffprobe_timeout_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FCS_")

    def allowed_private_result_hosts(self) -> set[str]:
        if self.env not in {"development", "test"}:
            return set()
        hosts = {item.strip().lower() for item in self.result_allowed_private_hosts.split(",") if item.strip()}
        return {host for host in hosts if host not in {"*", "0.0.0.0/0", "::/0"} and "/" not in host}


@lru_cache
def get_settings() -> Settings:
    return Settings()
