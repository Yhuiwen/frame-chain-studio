from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import ProviderConfigurationError
from app.providers.models import ProviderCapabilities, ProviderDefaults, ProviderInfo


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AsyncGenerationProvider] = {}
        self._configuration_errors: dict[str, str] = {}

    def register(self, provider: AsyncGenerationProvider) -> None:
        capabilities = provider.get_capabilities()
        provider_id = capabilities.provider_id
        if provider_id in self._providers or provider_id in self._configuration_errors:
            raise ProviderConfigurationError(f"Provider '{provider_id}' is already registered.")
        self._providers[provider_id] = provider

    def register_configuration_error(self, provider_id: str, display_name: str, message: str) -> None:
        del display_name
        if provider_id in self._providers or provider_id in self._configuration_errors:
            raise ProviderConfigurationError(f"Provider '{provider_id}' is already registered.")
        self._configuration_errors[provider_id] = message

    def get(self, provider_id: str) -> AsyncGenerationProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderConfigurationError(f"Provider '{provider_id}' is not registered.")
        return provider

    def list_capabilities(self) -> list[ProviderInfo]:
        infos = []
        for provider in self._providers.values():
            capabilities = provider.get_capabilities()
            config = getattr(provider, "config", None)
            infos.append(
                ProviderInfo(
                    provider_id=capabilities.provider_id,
                    display_name=capabilities.display_name,
                    capabilities=capabilities,
                    configured=True,
                    defaults=ProviderDefaults(
                        image_model=getattr(config, "default_image_model", None),
                        video_model=getattr(config, "default_video_model", None),
                        aspect_ratio=getattr(config, "default_aspect_ratio", "16:9"),
                        duration_seconds=getattr(config, "default_duration_seconds", None),
                    ),
                )
            )
        for provider_id, message in self._configuration_errors.items():
            infos.append(
                ProviderInfo(
                    provider_id=provider_id,
                    display_name=provider_id,
                    capabilities=ProviderCapabilities(provider_id=provider_id, display_name=provider_id),
                    configured=False,
                    configuration_error=message,
                )
            )
        return infos
