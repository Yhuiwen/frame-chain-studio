import os
from pathlib import Path

import pytest

from app.providers.async_base import AsyncGenerationProvider
from app.providers.config_loader import PROVIDER_CONFIG_ENV, load_provider_configs_from_file, load_registry_from_env
from app.providers.exceptions import ProviderConfigurationError
from app.providers.models import (
    ImageGenerationRequest,
    ProviderCancelResult,
    ProviderCapabilities,
    ProviderJobResult,
    ProviderSubmitResult,
    RemoteJobStatus,
    VideoGenerationRequest,
)
from app.providers.registry import ProviderRegistry


class DummyProvider(AsyncGenerationProvider):
    def __init__(self, provider_id: str = "dummy") -> None:
        self._capabilities = ProviderCapabilities(provider_id=provider_id, display_name="Dummy")

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        del request
        return ProviderSubmitResult(remote_job_id="x", remote_status=RemoteJobStatus.QUEUED)

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        del request
        return ProviderSubmitResult(remote_job_id="x", remote_status=RemoteJobStatus.QUEUED)

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        return ProviderJobResult(remote_job_id=remote_job_id, normalized_status=RemoteJobStatus.UNKNOWN)

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        return ProviderCancelResult(remote_job_id=remote_job_id, accepted=True)


def test_registry_register_get_list_and_errors() -> None:
    registry = ProviderRegistry()
    provider = DummyProvider()
    registry.register(provider)
    assert registry.get("dummy") is provider
    assert registry.list_capabilities()[0].provider_id == "dummy"
    with pytest.raises(ProviderConfigurationError):
        registry.register(DummyProvider())
    with pytest.raises(ProviderConfigurationError):
        registry.get("missing")


def test_registry_configuration_errors_are_isolated() -> None:
    one = ProviderRegistry()
    two = ProviderRegistry()
    one.register_configuration_error("bad", "Bad", "missing config")
    assert one.list_capabilities()[0].configured is False
    assert two.list_capabilities() == []


def test_provider_config_file_loading_and_secret_redaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
        {
          "providers": [
            {
              "provider_id": "fake-http",
              "display_name": "Fake HTTP",
              "base_url": "http://127.0.0.1:8090",
              "api_key": "super-secret",
              "capabilities": {
                "provider_id": "fake-http",
                "display_name": "Fake HTTP",
                "text_to_image": true
              },
              "mapping": {
                "submit_response": {"remote_job_id_path": "data.task_id", "status_path": "data.status"},
                "job_response": {"remote_job_id_path": "data.task_id", "status_path": "data.status"}
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    configs = load_provider_configs_from_file(config_path)
    assert configs[0].api_key is not None
    assert "super-secret" not in repr(configs[0])
    monkeypatch.setenv(PROVIDER_CONFIG_ENV, os.fspath(config_path))
    registry = load_registry_from_env()
    assert registry.list_capabilities()[0].configured is True


def test_provider_config_loading_errors(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigurationError):
        load_provider_configs_from_file(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(ProviderConfigurationError):
        load_provider_configs_from_file(invalid)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        """
        [
          {
            "provider_id": "dup",
            "display_name": "Dup",
            "base_url": "http://127.0.0.1",
            "capabilities": {"provider_id": "dup", "display_name": "Dup"},
            "mapping": {
              "submit_response": {"remote_job_id_path": "id", "status_path": "status"},
              "job_response": {"remote_job_id_path": "id", "status_path": "status"}
            }
          },
          {
            "provider_id": "dup",
            "display_name": "Dup",
            "base_url": "http://127.0.0.1",
            "capabilities": {"provider_id": "dup", "display_name": "Dup"},
            "mapping": {
              "submit_response": {"remote_job_id_path": "id", "status_path": "status"},
              "job_response": {"remote_job_id_path": "id", "status_path": "status"}
            }
          }
        ]
        """,
        encoding="utf-8",
    )
    with pytest.raises(ProviderConfigurationError):
        load_provider_configs_from_file(duplicate)
