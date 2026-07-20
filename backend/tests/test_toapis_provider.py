import json
from pathlib import Path

import httpx
import pytest

from app.providers.exceptions import ProviderCancellationError, ProviderInvalidResponseError, ProviderRateLimitError
from app.providers.models import AssetReference, ImageGenerationRequest, RemoteJobStatus, VideoGenerationRequest
from app.providers.toapis import IMAGE_MODEL, VIDEO_MODEL, ToApisProvider


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def image_request(**updates: object) -> ImageGenerationRequest:
    values = dict(provider_id="toapis", model="toapis-seedream-5", prompt="a frame", negative_prompt="blur", width=1920, height=1080, aspect_ratio="16:9", client_request_id="fcs-182-a1")
    values.update(updates)
    return ImageGenerationRequest.model_validate(values)


def video_request(**updates: object) -> VideoGenerationRequest:
    values = dict(provider_id="toapis", model="toapis-viduq3-pro", prompt="camera move", duration_seconds=4, fps=24, aspect_ratio="16:9", seed=123456, client_request_id="fcs-182-a1")
    values.update(updates)
    return VideoGenerationRequest.model_validate(values)


@pytest.mark.anyio
async def test_seedream_submit_and_poll_contract() -> None:
    seen: list[dict[str, object]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-secret"
        if request.method == "POST":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "data": {"task_id": "img-1", "status": "queued"}})
        return httpx.Response(200, json={"status": "completed", "result": {"data": [{"url": "https://cdn.example/result.png"}]}, "expires_at": "2026-07-21T00:00:00Z"})
    provider = ToApisProvider("test-secret", transport=httpx.MockTransport(handler), allow_live_submit=True)
    submitted = await provider.submit_image(image_request())
    assert submitted.remote_job_id == "image:img-1"
    assert seen[0]["model"] == IMAGE_MODEL
    assert seen[0]["metadata"] == {"resolution": "2K", "watermark": False}
    assert "negative_prompt" not in seen[0]
    assert seen[0]["client_business_id"] == "fcs-182-a1"
    result = await provider.get_job(submitted.remote_job_id)
    assert result.normalized_status == RemoteJobStatus.SUCCEEDED
    assert result.result_urls[0].url.endswith("result.png")
    await provider.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anchors", [0, 1, 2])
async def test_vidu_anchor_order(anchors: int) -> None:
    payload: dict[str, object] = {}
    def handler(request: httpx.Request) -> httpx.Response:
        payload.update(json.loads(request.content))
        return httpx.Response(200, json={"data": {"id": "vid-1", "status": "submitted"}})
    provider = ToApisProvider("secret", transport=httpx.MockTransport(handler), allow_live_submit=True)
    refs = [AssetReference(asset_id=1, url="https://cdn.example/start.png"), AssetReference(asset_id=2, url="https://cdn.example/end.png")]
    result = await provider.submit_video(video_request(start_frame=refs[0] if anchors else None, end_frame=refs[1] if anchors == 2 else None))
    assert result.remote_status == RemoteJobStatus.QUEUED
    assert payload["model"] == VIDEO_MODEL
    assert payload.get("image_urls", []) == [item.url for item in refs[:anchors]]
    assert payload["audio"] is False
    assert payload["resolution"] == "720p"
    assert payload["metadata"] == {"seed": 123456}
    await provider.aclose()


@pytest.mark.anyio
async def test_unknown_status_and_cancel_are_not_guessed() -> None:
    provider = ToApisProvider("secret", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"id": "x", "status": "mystery"}})), allow_live_submit=True)
    with pytest.raises(ProviderInvalidResponseError):
        await provider.submit_image(image_request())
    with pytest.raises(ProviderCancellationError):
        await provider.cancel_job("image:x")
    await provider.aclose()


@pytest.mark.anyio
async def test_rate_limit_is_retryable_and_secret_is_not_exposed() -> None:
    provider = ToApisProvider("very-secret-token", transport=httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "Bearer very-secret-token", "url": "https://x.test/file?signature=secret"}})), allow_live_submit=True)
    with pytest.raises(ProviderRateLimitError) as caught:
        await provider.submit_image(image_request())
    rendered = repr(caught.value.as_details())
    assert "very-secret-token" not in rendered
    assert "signature=secret" not in rendered
    await provider.aclose()


@pytest.mark.anyio
async def test_png_upload(tmp_path: Path) -> None:
    source = tmp_path / "frame.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="purpose"' in request.content and b"generation" in request.content
        return httpx.Response(200, json={"success": True, "data": {"id": "up-1", "url": "https://cdn.example/u.png", "mime_type": "image/png", "size": 28}})
    provider = ToApisProvider("secret", transport=httpx.MockTransport(handler), allow_live_submit=True)
    result = await provider.upload_asset(source, client_request_id="fcs-1-a1:asset:1")
    assert result.url == "https://cdn.example/u.png"
    await provider.aclose()
