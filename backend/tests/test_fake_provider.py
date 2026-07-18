import httpx
import pytest

from app.providers.exceptions import (
    ProviderCancellationError,
    ProviderInvalidResponseError,
    ProviderJobNotFoundError,
    ProviderRateLimitError,
    ProviderRemoteServerError,
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
from fake_provider.app import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def mapping_for(response_format: str) -> ProviderMappingConfig:
    if response_format == "B":
        response = ResponseMappingConfig(
            remote_job_id_path="job.id",
            status_path="job.state",
            result_urls_path="job.outputs",
        )
    elif response_format == "C":
        response = ResponseMappingConfig(
            remote_job_id_path="id",
            status_path="status_code",
            result_urls_path="result.files",
        )
    else:
        response = ResponseMappingConfig(
            remote_job_id_path="data.task_id",
            status_path="data.status",
            result_urls_path="data.output.video_url",
        )
    return ProviderMappingConfig(
        submit_response=response,
        job_response=response,
        cancel_response=response,
        image_request=RequestFieldMapping(fields={"prompt": "input.text"}),
        video_request=RequestFieldMapping(fields={"prompt": "input.text"}),
    )


def fake_provider(scenario: str = "success", response_format: str = "A") -> MappedAsyncHttpProvider:
    return MappedAsyncHttpProvider(
        MappedHttpProviderConfig(
            provider_id="fake-http",
            display_name="Fake HTTP",
            base_url="http://testserver",
            capabilities=ProviderCapabilities(
                provider_id="fake-http",
                display_name="Fake HTTP",
                text_to_image=True,
                image_to_video=True,
                first_last_frame_video=True,
                supports_cancel=True,
                supports_seed=True,
                max_reference_images=2,
            ),
            mapping=mapping_for(response_format),
        ),
        transport=httpx.ASGITransport(app=app),
        extra_headers={
            "X-Fake-Scenario": scenario,
            "X-Fake-Format": response_format,
            "X-Fake-Running-Polls": "1",
            "X-Fake-Request-Key": scenario,
            "X-Fake-Slow-Seconds": "0.01",
        },
    )


@pytest.mark.anyio
@pytest.mark.parametrize("response_format", ["A", "B", "C"])
async def test_fake_success_formats(response_format: str) -> None:
    provider = fake_provider("success", response_format)
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    first = await provider.get_job(submit.remote_job_id)
    second = await provider.get_job(submit.remote_job_id)
    await provider.aclose()
    assert submit.remote_job_id.startswith("fake-")
    assert first.normalized_status in {RemoteJobStatus.RUNNING, RemoteJobStatus.SUCCEEDED}
    assert second.normalized_status == RemoteJobStatus.SUCCEEDED
    assert second.result_urls


@pytest.mark.anyio
async def test_fake_image_submit_and_immediate_success() -> None:
    provider = fake_provider("immediate_success")
    submit = await provider.submit_image(
        ImageGenerationRequest(provider_id="fake-http", prompt="p", width=64, height=64)
    )
    job = await provider.get_job(submit.remote_job_id)
    await provider.aclose()
    assert job.normalized_status == RemoteJobStatus.SUCCEEDED


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario", "exception_type"),
    [
        ("submit_429_once", ProviderRateLimitError),
        ("submit_500_once", ProviderRemoteServerError),
        ("invalid_submit_response", ProviderInvalidResponseError),
        ("job_not_found", ProviderJobNotFoundError),
    ],
)
async def test_fake_submit_error_scenarios(scenario: str, exception_type: type[Exception]) -> None:
    provider = fake_provider(scenario)
    with pytest.raises(exception_type):
        await provider.submit_image(ImageGenerationRequest(provider_id="fake-http", prompt="p", width=64, height=64))
    await provider.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("permanent_failure", RemoteJobStatus.FAILED),
        ("unknown_status", RemoteJobStatus.UNKNOWN),
    ],
)
async def test_fake_poll_status_scenarios(scenario: str, expected: RemoteJobStatus) -> None:
    provider = fake_provider(scenario)
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    await provider.get_job(submit.remote_job_id)
    result = await provider.get_job(submit.remote_job_id)
    await provider.aclose()
    assert result.normalized_status == expected


@pytest.mark.anyio
async def test_fake_poll_500_invalid_status_cancel_and_slow() -> None:
    provider = fake_provider("poll_500_once")
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    with pytest.raises(ProviderRemoteServerError):
        await provider.get_job(submit.remote_job_id)
    await provider.aclose()

    provider = fake_provider("invalid_status_response")
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    with pytest.raises(ProviderInvalidResponseError):
        await provider.get_job(submit.remote_job_id)
    await provider.aclose()

    provider = fake_provider("cancel_success")
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    cancel = await provider.cancel_job(submit.remote_job_id)
    await provider.aclose()
    assert cancel.remote_status == RemoteJobStatus.CANCELLED

    provider = fake_provider("cancel_not_supported")
    submit = await provider.submit_video(
        VideoGenerationRequest(provider_id="fake-http", prompt="p", duration_seconds=1, fps=24)
    )
    with pytest.raises(ProviderCancellationError):
        await provider.cancel_job(submit.remote_job_id)
    await provider.aclose()

    provider = fake_provider("slow_response")
    submit = await provider.submit_image(
        ImageGenerationRequest(provider_id="fake-http", prompt="p", width=64, height=64)
    )
    await provider.aclose()
    assert submit.remote_job_id.startswith("fake-")
