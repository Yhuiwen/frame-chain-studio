from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import ProviderConfigurationError
from app.providers.models import ProviderCapabilities, ProviderInfo


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
        infos = [
            ProviderInfo(
                provider_id=provider.get_capabilities().provider_id,
                display_name=provider.get_capabilities().display_name,
                capabilities=provider.get_capabilities(),
                configured=True,
            )
            for provider in self._providers.values()
        ]
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
