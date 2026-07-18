import httpx
import pytest

from app.providers.exceptions import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderRemoteServerError,
    ProviderTimeoutError,
)
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import (
    ImageGenerationRequest,
    MappedHttpProviderConfig,
    ProviderCapabilities,
    ProviderMappingConfig,
    RemoteJobStatus,
    RequestFieldMapping,
    ResponseMappingConfig,
    VideoGenerationRequest,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def provider_config() -> MappedHttpProviderConfig:
    response_mapping = ResponseMappingConfig(
        remote_job_id_path="data.task_id",
        status_path="data.status",
        result_urls_path="data.output.video_url",
    )
    return MappedHttpProviderConfig(
        provider_id="fake-http",
        display_name="Fake HTTP",
        base_url="http://provider.test",
        api_key="secret-token",
        capabilities=ProviderCapabilities(
            provider_id="fake-http",
            display_name="Fake HTTP",
            text_to_image=True,
            image_to_video=True,
            first_last_frame_video=True,
            supports_seed=True,
            supports_cancel=True,
            max_reference_images=2,
        ),
        mapping=ProviderMappingConfig(
            submit_response=response_mapping,
            job_response=response_mapping,
            cancel_response=response_mapping,
            image_request=RequestFieldMapping(
                fields={"prompt": "input.text", "width": "parameters.width", "height": "parameters.height"},
                fixed_fields={"parameters.output_format": "png"},
            ),
            video_request=RequestFieldMapping(
                fields={"prompt": "input.text", "duration_seconds": "input.duration", "fps": "input.fps"},
                fixed_fields={"parameters.output_format": "mp4"},
            ),
        ),
    )


def mock_provider(status_code: int, payload: object, *, text: str | None = None) -> MappedAsyncHttpProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-token"
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=payload)

    return MappedAsyncHttpProvider(provider_config(), transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_submit_image_video_get_job_and_cancel_success() -> None:
    provider = mock_provider(200, {"data": {"task_id": "remote-1", "status": "running", "output": {"video_url": "u"}}})
    image = await provider.submit_image(
        ImageGenerationRequest(provider_id="fake-http", prompt="p", width=64, height=64)
    )
    video = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=2, fps=24)
    )
    job = await provider.get_job("remote-1")
    cancel = await provider.cancel_job("remote-1")
    await provider.aclose()
    assert image.remote_job_id == "remote-1"
    assert video.remote_status == RemoteJobStatus.RUNNING
    assert job.result_urls[0].url == "u"
    assert cancel.remote_status == RemoteJobStatus.RUNNING


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "error_type", "retryable"),
    [
        (400, ProviderInvalidResponseError, False),
        (401, ProviderAuthenticationError, False),
        (403, ProviderAuthenticationError, False),
        (429, ProviderRateLimitError, True),
        (500, ProviderRemoteServerError, True),
        (502, ProviderRemoteServerError, True),
        (503, ProviderRemoteServerError, True),
        (504, ProviderRemoteServerError, True),
    ],
)
async def test_http_status_errors(status_code: int, error_type: type[Exception], retryable: bool) -> None:
    provider = mock_provider(status_code, {"error": {"api_key": "secret-token", "message": "x" * 3000}})
    with pytest.raises(error_type) as exc_info:
        await provider.get_job("remote-1")
    await provider.aclose()
    error = exc_info.value
    assert getattr(error, "retryable") is retryable
    assert "secret-token" not in str(getattr(error, "details", {}))
    assert len(str(getattr(error, "details", {}))) < 2500


@pytest.mark.anyio
async def test_timeout_network_non_json_missing_fields_and_secret_repr() -> None:
    async def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    provider = MappedAsyncHttpProvider(provider_config(), transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(ProviderTimeoutError):
        await provider.get_job("remote-1")
    await provider.aclose()

    async def network_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    provider = MappedAsyncHttpProvider(provider_config(), transport=httpx.MockTransport(network_handler))
    with pytest.raises(ProviderNetworkError):
        await provider.get_job("remote-1")
    await provider.aclose()

    provider = mock_provider(200, {}, text="not json")
    with pytest.raises(ProviderInvalidResponseError):
        await provider.get_job("remote-1")
    await provider.aclose()

    provider = mock_provider(200, {"data": {"status": "queued"}})
    with pytest.raises(ProviderInvalidResponseError):
        await provider.submit_image(
            ImageGenerationRequest(provider_id="fake-http", prompt="p", width=64, height=64)
        )
    await provider.aclose()
    assert "secret-token" not in repr(provider_config())
