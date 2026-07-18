from abc import ABC, abstractmethod

from app.providers.models import (
    ImageGenerationRequest,
    ProviderCancelResult,
    ProviderCapabilities,
    ProviderJobResult,
    ProviderSubmitResult,
    VideoGenerationRequest,
)


class AsyncGenerationProvider(ABC):
    """Phase 2 async provider protocol. It is intentionally database-free."""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        raise NotImplementedError

    @abstractmethod
    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        raise NotImplementedError

    @abstractmethod
    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        raise NotImplementedError

    @abstractmethod
    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        raise NotImplementedError
