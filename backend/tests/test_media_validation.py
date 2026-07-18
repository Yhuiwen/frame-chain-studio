from pathlib import Path

import pytest
from PIL import Image

from app.media.validation import MediaValidationError, validate_image, validate_media, validate_video
from app.models.entities import ResultMediaKind


def test_validate_image_accepts_png_jpeg_and_webp(tmp_path: Path) -> None:
    for image_format, suffix, mime_type in [
        ("PNG", ".png", "image/png"),
        ("JPEG", ".jpg", "image/jpeg"),
        ("WEBP", ".webp", "image/webp"),
    ]:
        path = tmp_path / f"image{suffix}"
        Image.new("RGB", (16, 12), color=(12, 34, 56)).save(path, format=image_format)
        metadata = validate_image(path, max_pixels=1_000_000)
        assert metadata.mime_type == mime_type
        assert metadata.width == 16
        assert metadata.height == 12


def test_validate_image_rejects_corrupt_html_empty_and_svg(tmp_path: Path) -> None:
    for name, data in {
        "corrupt.png": b"not an image",
        "page.png": b"<html>not media</html>",
        "empty.png": b"",
        "vector.svg": b"<svg></svg>",
    }.items():
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(MediaValidationError):
            validate_image(path, max_pixels=1_000_000)


def test_validate_image_rejects_too_many_pixels(tmp_path: Path) -> None:
    path = tmp_path / "large.png"
    Image.new("RGB", (100, 100)).save(path)
    with pytest.raises(MediaValidationError):
        validate_image(path, max_pixels=10)


def test_validate_video_accepts_fixture() -> None:
    metadata = validate_video(Path("tests/fixtures/mock-video.mp4"), timeout_seconds=10)
    assert metadata.media_kind == ResultMediaKind.VIDEO
    assert metadata.width and metadata.width > 0
    assert metadata.height and metadata.height > 0
    assert metadata.duration_seconds and metadata.duration_seconds > 0


def test_validate_video_rejects_non_video(tmp_path: Path) -> None:
    path = tmp_path / "fake.mp4"
    path.write_text("<html>not video</html>")
    with pytest.raises(MediaValidationError):
        validate_video(path, timeout_seconds=10)


def test_validate_media_dispatches_by_expected_kind() -> None:
    metadata = validate_media(
        Path("tests/fixtures/mock-keyframe.png"),
        expected_kind=ResultMediaKind.IMAGE,
        max_image_pixels=10_000_000,
        ffprobe_timeout_seconds=10,
    )
    assert metadata.media_kind == ResultMediaKind.IMAGE
