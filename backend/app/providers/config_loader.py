import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.core.config import get_settings, resolve_backend_path
from app.providers.exceptions import ProviderConfigurationError
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import MappedHttpProviderConfig
from app.providers.registry import ProviderRegistry
from app.providers.toapis import ToApisProvider

if TYPE_CHECKING:
    from sqlmodel import Session

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
    settings = get_settings()
    config_file = settings.provider_config_file
    if config_file is None:
        raw_env = os.getenv(PROVIDER_CONFIG_ENV)
        config_file = resolve_backend_path(raw_env) if raw_env else None
    if config_file is None:
        return registry
    for config in load_provider_configs_from_file(Path(config_file)):
        registry.register(MappedAsyncHttpProvider(config))
    return registry


def load_registry(session: "Session | None" = None) -> ProviderRegistry:
    registry = load_registry_from_env()
    if session is None:
        return registry
    from app.services.provider_management import db_profile_to_http_config
    from app.models.entities import ProviderAdapterType, ProviderProfile
    from sqlmodel import col, select

    profiles = session.exec(
        select(ProviderProfile).where(
            col(ProviderProfile.enabled).is_(True),
            col(ProviderProfile.archived_at).is_(None),
            ProviderProfile.adapter_type != ProviderAdapterType.FAKE,
        )
    ).all()
    for profile in profiles:
        if profile.adapter_type == ProviderAdapterType.TOAPIS:
            api_key = os.getenv(profile.secret_env_var) if profile.secret_env_var else None
            if api_key:
                # The long-lived Worker validates the durable live gate immediately before each
                # task. Do not freeze the startup-time flag into its Provider instance.
                registry.register(ToApisProvider(api_key, base_url=profile.base_url, allow_live_submit=True))
            else:
                registry.register_configuration_error(profile.provider_key, profile.display_name, "TOAPIS_API_KEY is not configured.")
        else:
            registry.register(MappedAsyncHttpProvider(db_profile_to_http_config(session, profile)))
    return registry
