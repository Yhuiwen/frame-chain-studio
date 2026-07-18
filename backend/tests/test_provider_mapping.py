import pytest

from app.providers.exceptions import ProviderInvalidResponseError, ProviderUnsupportedCapabilityError
from app.providers.mapping import (
    apply_request_mapping,
    extract_result_urls,
    get_by_path,
    normalize_remote_status,
    require_by_path,
)
from app.providers.models import (
    AssetReference,
    ImageGenerationRequest,
    ProviderCapabilities,
    RemoteJobStatus,
    ResponseMappingConfig,
    VideoGenerationRequest,
    validate_request_capabilities,
)


def test_get_by_path_supports_dict_list_defaults_and_null() -> None:
    data = {"data": {"items": [{"download-url": None}, {"download-url": "http://x"}]}}
    assert get_by_path(data, "data.items.1.download-url") == "http://x"
    assert get_by_path(data, "data.items.0.download-url") is None
    assert get_by_path(data, "data.missing", "fallback") == "fallback"


def test_required_path_and_unsafe_paths_raise_provider_error() -> None:
    with pytest.raises(ProviderInvalidResponseError):
        require_by_path({"data": {}}, "data.task_id")
    with pytest.raises(ProviderInvalidResponseError):
        get_by_path({"data": []}, "data.items[0]")
    with pytest.raises(ProviderInvalidResponseError):
        get_by_path({}, ".".join(["x"] * 33))
    with pytest.raises(ProviderInvalidResponseError):
        get_by_path([{"x": 1}], "bad")


def test_request_mapping_nested_fixed_none_and_conflict() -> None:
    source = {
        "prompt": "a girl walks into a laboratory",
        "negative_prompt": None,
        "duration_seconds": 5,
        "start_frame": {"url": "http://fake/start.png"},
        "end_frame": {"url": "http://fake/end.png"},
        "seed": 42,
    }
    mapped = apply_request_mapping(
        source,
        {
            "prompt": "input.text",
            "negative_prompt": "input.negative",
            "duration_seconds": "input.duration",
            "start_frame.url": "input.first_frame_url",
            "end_frame.url": "input.last_frame_url",
            "seed": "parameters.seed",
        },
        {"parameters.output_format": "mp4"},
    )
    assert mapped == {
        "input": {
            "text": "a girl walks into a laboratory",
            "duration": 5,
            "first_frame_url": "http://fake/start.png",
            "last_frame_url": "http://fake/end.png",
        },
        "parameters": {"seed": 42, "output_format": "mp4"},
    }
    assert "input" not in source
    with pytest.raises(ProviderInvalidResponseError):
        apply_request_mapping({"a": 1, "b": 2}, {"a": "x", "b": "x.y"})


def test_status_mapping_all_known_unknown_numeric_and_invalid() -> None:
    config = ResponseMappingConfig(remote_job_id_path="id", status_path="status")
    assert normalize_remote_status("PENDING", config) == RemoteJobStatus.QUEUED
    assert normalize_remote_status("processing", config) == RemoteJobStatus.RUNNING
    assert normalize_remote_status("success", config) == RemoteJobStatus.SUCCEEDED
    assert normalize_remote_status("error", config) == RemoteJobStatus.FAILED
    assert normalize_remote_status("canceled", config) == RemoteJobStatus.CANCELLED
    assert normalize_remote_status(2, config) == RemoteJobStatus.SUCCEEDED
    assert normalize_remote_status("7", config) == RemoteJobStatus.UNKNOWN
    assert normalize_remote_status(None, config) == RemoteJobStatus.UNKNOWN
    assert normalize_remote_status({"state": "running"}, config) == RemoteJobStatus.UNKNOWN


def test_result_url_mapping_variants() -> None:
    assert extract_result_urls(
        {"data": {"url": "http://one"}},
        ResponseMappingConfig(remote_job_id_path="id", status_path="status", result_urls_path="data.url"),
    )[0].url == "http://one"
    assert [
        item.url
        for item in extract_result_urls(
            {"data": {"urls": ["http://one", "http://two"]}},
            ResponseMappingConfig(remote_job_id_path="id", status_path="status", result_urls_path="data.urls"),
        )
    ] == ["http://one", "http://two"]
    assert [
        item.url
        for item in extract_result_urls(
            {"result": {"files": [{"download_url": "http://one"}, {"file": {"url": "http://two"}}]}},
            ResponseMappingConfig(remote_job_id_path="id", status_path="status", result_urls_path="result.files"),
        )
    ] == ["http://one", "http://two"]
    assert extract_result_urls(
        {"result": {"files": {"download_url": "http://bad"}}},
        ResponseMappingConfig(remote_job_id_path="id", status_path="status", result_urls_path="result.files"),
    ) == []
    assert [
        item.url
        for item in extract_result_urls(
            {"data": {"output": {"video_url": "http://video"}}},
            ResponseMappingConfig(
                remote_job_id_path="id",
                status_path="status",
                result_urls_path=["data.output.image_url", "data.output.video_url"],
            ),
        )
    ] == ["http://video"]


def test_capability_validation() -> None:
    capabilities = ProviderCapabilities(
        provider_id="fake",
        display_name="Fake",
        text_to_image=True,
        image_to_video=True,
        first_last_frame_video=True,
        max_reference_images=2,
        max_duration_seconds=4,
    )
    validate_request_capabilities(
        ImageGenerationRequest(provider_id="fake", prompt="p", width=64, height=64),
        capabilities,
    )
    validate_request_capabilities(
        VideoGenerationRequest(
            provider_id="fake",
            prompt="p",
            duration_seconds=4,
            fps=24,
            start_frame=AssetReference(url="http://fake/a.png"),
            end_frame=AssetReference(url="http://fake/b.png"),
        ),
        capabilities,
    )
    with pytest.raises(ProviderUnsupportedCapabilityError):
        validate_request_capabilities(
            VideoGenerationRequest(provider_id="fake", prompt="p", duration_seconds=5, fps=24),
            capabilities,
        )
