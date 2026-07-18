from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def resolve_backend_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (BACKEND_ROOT / path).resolve()


def normalize_sqlite_url(url: str) -> str:
    if url in {"sqlite://", "sqlite:///:memory:"}:
        return url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url.removeprefix(prefix)
    if raw_path in {":memory:", ""}:
        return url
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (BACKEND_ROOT / path).resolve()
    return f"sqlite:///{resolved.as_posix()}"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


class Settings(BaseSettings):
    app_name: str = "Frame Chain Studio API"
    database_url: str = "sqlite:///./data/frame_chain.db"
    storage_root: Path | None = None
    storage_dir: Path = Path("./data/storage")
    fixture_dir: Path = Path("./tests/fixtures")
    provider_config_file: Path | None = None
    log_dir: Path = Path("./data/logs")
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
    default_image_provider_id: str | None = None
    default_video_provider_id: str | None = None
    worker_heartbeat_seconds: int = 10
    worker_stale_after_seconds: int = 45
    default_image_model: str | None = None
    default_video_model: str | None = None
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 5173
    fake_provider_host: str = "127.0.0.1"
    fake_provider_port: int = 8090
    render_worker_lease_seconds: int = 300
    render_width: int = 1920
    render_height: int = 1080
    render_fps: int = 24
    render_video_codec: str = "libx264"
    render_audio_codec: str = "aac"
    render_temp_file_ttl_hours: int = 24

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FCS_")

    @model_validator(mode="after")
    def normalize_paths(self) -> "Settings":
        self.database_url = normalize_sqlite_url(self.database_url)
        if self.storage_root is not None:
            self.storage_dir = self.storage_root
        self.storage_dir = resolve_backend_path(self.storage_dir) or self.storage_dir
        self.fixture_dir = resolve_backend_path(self.fixture_dir) or self.fixture_dir
        self.log_dir = resolve_backend_path(self.log_dir) or self.log_dir
        self.provider_config_file = resolve_backend_path(self.provider_config_file)
        return self

    def allowed_private_result_hosts(self) -> set[str]:
        if self.env not in {"development", "test"}:
            return set()
        hosts = {item.strip().lower() for item in self.result_allowed_private_hosts.split(",") if item.strip()}
        return {host for host in hosts if host not in {"*", "0.0.0.0/0", "::/0"} and "/" not in host}

    def safe_summary(self) -> dict[str, str | int | None]:
        return {
            "database": _safe_database_label(self.database_url),
            "storage": display_path(self.storage_dir),
            "fixtures": display_path(self.fixture_dir),
            "provider_config": display_path(self.provider_config_file) if self.provider_config_file else None,
            "backend_port": self.backend_port,
            "frontend_port": self.frontend_port,
            "fake_provider_port": self.fake_provider_port,
        }


def _safe_database_label(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url.split("://", 1)[0]
    path = Path(url.removeprefix("sqlite:///"))
    return f"sqlite:///{display_path(path)}"


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=BACKEND_ROOT / ".env")
