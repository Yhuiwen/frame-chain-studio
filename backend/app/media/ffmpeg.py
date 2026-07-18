import shutil
import subprocess
from pathlib import Path

from app.core.errors import AppError


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise AppError("MEDIA_TOOL_MISSING", f"{name} is required but was not found.", 500)
    return binary


def create_test_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x314159:s=1280x720:d=1",
        "-frames:v",
        "1",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def create_test_video(path: Path, duration_seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=1280x720:rate=24:duration={duration_seconds}",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def extract_tail_frame(video_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-sseof",
        "-0.05",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def assert_probeable(path: Path) -> None:
    ffprobe = require_binary("ffprobe")
    command = [ffprobe, "-v", "error", "-show_format", "-show_streams", str(path)]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
