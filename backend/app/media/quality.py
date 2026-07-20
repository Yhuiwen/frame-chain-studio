import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from app.media.ffmpeg import require_binary
from app.media.validation import MediaMetadata, validate_video


@dataclass(frozen=True)
class ImageComparison:
    dhash_distance: int
    pixel_mae: float
    brightness_diff: float
    color_shift: float
    aspect_ratio_diff: float
    reference_rgb: tuple[float, float, float]
    actual_rgb: tuple[float, float, float]


@dataclass(frozen=True)
class VideoSegment:
    start: float
    end: float
    duration: float


def extract_first_frame(video_path: Path, output_path: Path, *, timeout_seconds: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            require_binary("ffmpeg"),
            "-y",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output_path),
        ],
        timeout_seconds=timeout_seconds,
    )


def extract_last_frame(video_path: Path, output_path: Path, *, timeout_seconds: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            require_binary("ffmpeg"),
            "-y",
            "-sseof",
            "-0.05",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output_path),
        ],
        timeout_seconds=timeout_seconds,
    )


def compare_images(reference_path: Path, actual_path: Path, *, size: tuple[int, int] = (64, 64)) -> ImageComparison:
    with Image.open(reference_path) as ref_raw, Image.open(actual_path) as actual_raw:
        ref_rgb = ref_raw.convert("RGB")
        actual_rgb = actual_raw.convert("RGB")
        ref_aspect = ref_rgb.width / ref_rgb.height
        actual_aspect = actual_rgb.width / actual_rgb.height
        ref = ref_rgb.resize(size)
        actual = actual_rgb.resize(size)
        diff = ImageChops.difference(ref, actual)
        channel_mean = ImageStat.Stat(diff).mean
        ref_mean = ImageStat.Stat(ref).mean
        actual_mean = ImageStat.Stat(actual).mean
    return ImageComparison(
        dhash_distance=_hamming_distance(_dhash(ref), _dhash(actual)),
        pixel_mae=sum(channel_mean) / (len(channel_mean) * 255),
        brightness_diff=abs(sum(ref_mean) - sum(actual_mean)) / (len(ref_mean) * 255),
        color_shift=max(abs(left - right) for left, right in zip(ref_mean, actual_mean, strict=True)) / 255,
        aspect_ratio_diff=abs(ref_aspect - actual_aspect),
        reference_rgb=_rgb_tuple(ref_mean),
        actual_rgb=_rgb_tuple(actual_mean),
    )


def probe_video(path: Path, *, timeout_seconds: int) -> MediaMetadata:
    return validate_video(path, timeout_seconds=timeout_seconds)


def detect_black_segments(path: Path, *, min_duration: float, timeout_seconds: int) -> list[VideoSegment]:
    completed = _run_ffmpeg(
        [
            require_binary("ffmpeg"),
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            f"blackdetect=d={min_duration}:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout_seconds=timeout_seconds,
        check=False,
    )
    return _segments(completed.stderr.decode("utf-8", errors="replace"), "black")


def detect_freeze_segments(path: Path, *, min_duration: float, timeout_seconds: int) -> list[VideoSegment]:
    completed = _run_ffmpeg(
        [
            require_binary("ffmpeg"),
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            f"freezedetect=n=-60dB:d={min_duration}",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout_seconds=timeout_seconds,
        check=False,
    )
    return _segments(completed.stderr.decode("utf-8", errors="replace"), "freeze")


def verify_decode(path: Path, *, timeout_seconds: int) -> str | None:
    completed = _run_ffmpeg(
        [require_binary("ffmpeg"), "-v", "error", "-i", str(path), "-f", "null", "-"],
        timeout_seconds=timeout_seconds,
        check=False,
    )
    if completed.returncode == 0:
        return None
    return completed.stderr.decode("utf-8", errors="replace")[:500]


def _dhash(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8))
    pixels = list(gray.getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            value <<= 1
            if pixels[row * 9 + col] > pixels[row * 9 + col + 1]:
                value |= 1
    return value


def _rgb_tuple(values: list[float]) -> tuple[float, float, float]:
    padded = [*values, 0.0, 0.0, 0.0]
    return (round(padded[0], 3), round(padded[1], 3), round(padded[2], 3))


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _segments(text: str, prefix: str) -> list[VideoSegment]:
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    starts: list[float] = []
    segments: list[VideoSegment] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        start_match = re.search(rf"{prefix}_start:(?P<value>{number})", line)
        if start_match:
            starts.append(float(start_match.group("value")))
        end_match = re.search(rf"{prefix}_end:(?P<end>{number}).*?{prefix}_duration:(?P<duration>{number})", line)
        if not end_match:
            continue
        end = float(end_match.group("end"))
        duration = float(end_match.group("duration"))
        start = starts.pop(0) if starts else max(0.0, end - duration)
        segments.append(VideoSegment(start, end, duration))
    return segments


def _run_ffmpeg(command: list[str], *, timeout_seconds: int, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError("FFmpeg command failed.")
    return completed
