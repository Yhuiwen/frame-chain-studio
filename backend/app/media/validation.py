import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.media.ffmpeg import require_binary
from app.models.entities import ResultMediaKind


class MediaValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class MediaMetadata:
    media_kind: ResultMediaKind
    mime_type: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    frame_count: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None


def validate_image(path: Path, *, max_pixels: int) -> MediaMetadata:
    if not path.exists() or path.stat().st_size == 0:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Image file is empty or missing.")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            frame_count = getattr(image, "n_frames", 1)
            if frame_count and int(frame_count) > 1:
                raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Animated images are not accepted.")
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Image dimensions exceed configured limits.")
            image_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Image file is not a valid raster image.") from exc
    mime_by_format = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }
    mime_type = mime_by_format.get(image_format)
    if mime_type is None:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", f"Unsupported image format {image_format or 'unknown'}.")
    return MediaMetadata(
        media_kind=ResultMediaKind.IMAGE,
        mime_type=mime_type,
        width=width,
        height=height,
        frame_count=int(frame_count or 1),
    )


def validate_video(path: Path, *, timeout_seconds: int) -> MediaMetadata:
    if not path.exists() or path.stat().st_size == 0:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Video file is empty or missing.")
    ffprobe = require_binary("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "FFprobe timed out.") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[:500]
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", f"FFprobe failed: {stderr}")
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "FFprobe returned invalid JSON.") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "FFprobe stream metadata is missing.")
    video_stream = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    if not isinstance(video_stream, dict):
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Video result has no video stream.")
    width = _positive_int(video_stream.get("width"))
    height = _positive_int(video_stream.get("height"))
    if width is None or height is None:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Video dimensions are invalid.")
    duration = _positive_float(video_stream.get("duration"))
    if duration is None:
        format_payload = payload.get("format") if isinstance(payload, dict) else None
        if isinstance(format_payload, dict):
            duration = _positive_float(format_payload.get("duration"))
    if duration is None:
        raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Video duration is invalid.")
    audio_stream = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), None)
    return MediaMetadata(
        media_kind=ResultMediaKind.VIDEO,
        mime_type="video/mp4",
        width=width,
        height=height,
        duration_seconds=duration,
        fps=_parse_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        frame_count=_positive_int(video_stream.get("nb_frames")),
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name") or "") if isinstance(audio_stream, dict) else None,
    )


def validate_media(path: Path, *, expected_kind: ResultMediaKind, max_image_pixels: int, ffprobe_timeout_seconds: int) -> MediaMetadata:
    if expected_kind == ResultMediaKind.IMAGE:
        return validate_image(path, max_pixels=max_image_pixels)
    if expected_kind == ResultMediaKind.VIDEO:
        return validate_video(path, timeout_seconds=ffprobe_timeout_seconds)
    raise MediaValidationError("MEDIA_VALIDATION_ERROR", "Unsupported expected media kind.")


def _positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_rate(value: object) -> float | None:
    text = str(value or "")
    if "/" in text:
        left, right = text.split("/", 1)
        numerator = _positive_float(left)
        denominator = _positive_float(right)
        if numerator and denominator:
            return numerator / denominator
        return None
    return _positive_float(text)
