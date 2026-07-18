import json
import os
from pathlib import Path

from pydantic import ValidationError

from app.providers.exceptions import ProviderConfigurationError
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import MappedHttpProviderConfig
from app.providers.registry import ProviderRegistry

PROVIDER_CONFIG_ENV = "FCS_PROVIDER_CONFIG_FILE"


def load_provider_configs_from_file(path: Path) -> list[MappedHttpProviderConfig]:
    if not path.exists():
        raise ProviderConfigurationError(f"Provider config file '{path}' does not exist.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProviderConfigurationError(f"Provider config file '{path}' is not valid JSON.") from exc
    items = raw.get("providers") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ProviderConfigurationError("Provider config must be a list or contain a providers list.")
    try:
        configs = [MappedHttpProviderConfig.model_validate(item) for item in items]
    except ValidationError as exc:
        raise ProviderConfigurationError("Provider config validation failed.", details={"errors": exc.errors()}) from exc
    seen: set[str] = set()
    for config in configs:
        if config.provider_id in seen:
            raise ProviderConfigurationError(f"Provider '{config.provider_id}' is duplicated in config.")
        seen.add(config.provider_id)
    return configs


def load_registry_from_env() -> ProviderRegistry:
    registry = ProviderRegistry()
    config_file = os.getenv(PROVIDER_CONFIG_ENV)
    if not config_file:
        return registry
    for config in load_provider_configs_from_file(Path(config_file)):
        registry.register(MappedAsyncHttpProvider(config))
    return registry
