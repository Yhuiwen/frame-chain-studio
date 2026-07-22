from hashlib import sha256
from pathlib import Path
import shutil
import subprocess

import pytest

from app.media.ffmpeg import require_binary
from app.media.scene_cut import (
    SceneCutAnalysisError,
    SceneCutConfig,
    _frame_metrics,
    analyze_video,
)


def _video(path: Path, kind: str) -> None:
    ffmpeg = require_binary("ffmpeg")
    if kind == "static":
        inputs = ["-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2"]
        tail = ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "testsrc":
        inputs = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2"]
        tail = ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "hard":
        inputs = [
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=1",
        ]
        tail = ["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "fade":
        inputs = ["-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2"]
        tail = ["-vf", "fade=t=out:st=0.5:d=1.5", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "crossfade":
        inputs = [
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=1.5",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=1.5",
        ]
        tail = ["-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=1:offset=0.5", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "flash":
        inputs = ["-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2"]
        tail = ["-vf", "drawbox=color=white:t=fill:enable='eq(n,24)'", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind == "black_flash":
        inputs = ["-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2"]
        tail = ["-vf", "drawbox=color=black:t=fill:enable='eq(n,24)'", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    elif kind in {"two_hard", "near_start", "near_end"}:
        durations = {"two_hard": (0.75, 0.5, 0.75), "near_start": (0.25, 1.75, 0), "near_end": (1.75, 0.25, 0)}[kind]
        colors = ("red", "blue", "green")
        active = [(color, duration) for color, duration in zip(colors, durations, strict=True) if duration]
        inputs = [value for color, duration in active for value in ("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d={duration}")]
        labels = "".join(f"[{index}:v]" for index in range(len(active)))
        tail = ["-filter_complex", f"{labels}concat=n={len(active)}:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    else:
        raise AssertionError(kind)
    completed = subprocess.run([ffmpeg, "-y", *inputs, *tail], capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def _analyze(path: Path, *, asset_id: int = 1, config: SceneCutConfig = SceneCutConfig()):
    return analyze_video(
        path,
        asset_id=asset_id,
        asset_sha256=sha256(path.read_bytes()).hexdigest(),
        duration_seconds=2,
        source_fps="24/1",
        timeout_seconds=20,
        config=config,
    )


def test_sampling_is_deterministic_and_independent_of_name_and_asset_id(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    renamed = tmp_path / "renamed.bin"
    _video(source, "hard")
    shutil.copyfile(source, renamed)
    first = _analyze(source, asset_id=10)
    second = _analyze(source, asset_id=10)
    renamed_result = _analyze(renamed, asset_id=11)
    assert first == second
    assert [item.timestamp_seconds for item in first.samples] == [item.timestamp_seconds for item in renamed_result.samples]
    assert [item.frame_sha256 for item in first.samples] == [item.frame_sha256 for item in renamed_result.samples]
    assert first.events[0].timestamp_seconds == renamed_result.events[0].timestamp_seconds
    changed = _analyze(source, config=SceneCutConfig(analysis_fps=6))
    assert first.evidence()["sample_manifest"]["manifest_sha256"] != changed.evidence()["sample_manifest"]["manifest_sha256"]


def test_metrics_are_bounded_rounded_and_distinguish_frames() -> None:
    config = SceneCutConfig(width=2, height=1)
    black = bytes([0, 0, 0] * 2)
    white = bytes([255, 255, 255] * 2)
    assert _frame_metrics(black, black, config) == (0, 0)
    pixel, histogram = _frame_metrics(black, white, config)
    assert pixel == 1
    assert histogram == 1


@pytest.mark.parametrize("kind", ["static", "testsrc", "fade", "crossfade"])
def test_no_cut_and_gradual_fixtures_do_not_produce_hard_cuts(tmp_path: Path, kind: str) -> None:
    path = tmp_path / f"{kind}.mp4"
    _video(path, kind)
    result = _analyze(path)
    assert result.hard_cut_count == 0


def test_hard_cut_is_blocking_and_within_one_sample_interval(tmp_path: Path) -> None:
    path = tmp_path / "hard.mp4"
    _video(path, "hard")
    result = _analyze(path)
    assert result.hard_cut_count == 1
    event = next(item for item in result.events if item.classification == "HARD_CUT")
    assert event.blocking is True
    assert abs(float(event.timestamp_seconds) - 1.0) <= 1 / 12


def test_single_frame_flash_is_review_candidate_not_hard_cut(tmp_path: Path) -> None:
    path = tmp_path / "flash.mp4"
    _video(path, "flash")
    result = _analyze(path)
    assert result.hard_cut_count == 0
    assert result.review_candidate_count == 2


@pytest.mark.parametrize("kind", ["flash", "black_flash"])
def test_single_frame_anomaly_returns_to_scene_and_is_not_hard_cut(tmp_path: Path, kind: str) -> None:
    path = tmp_path / f"{kind}.mp4"
    _video(path, kind)
    result = _analyze(path)
    assert result.hard_cut_count == 0
    assert result.review_candidate_count == 2


@pytest.mark.parametrize(("kind", "count", "timestamp"), [("two_hard", 2, 0.75), ("near_start", 1, 0.25), ("near_end", 1, 1.75)])
def test_multiple_and_boundary_hard_cuts(tmp_path: Path, kind: str, count: int, timestamp: float) -> None:
    path = tmp_path / f"{kind}.mp4"
    _video(path, kind)
    result = _analyze(path)
    assert result.hard_cut_count == count
    assert abs(float(next(event for event in result.events if event.blocking).timestamp_seconds) - timestamp) <= 1 / 12


def test_errors_and_limits_are_explicit(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    with pytest.raises(SceneCutAnalysisError, match="SCENE_CUT_VIDEO_MISSING"):
        analyze_video(missing, asset_id=1, asset_sha256="x", duration_seconds=2, source_fps="24/1", timeout_seconds=20)
    path = tmp_path / "video.mp4"
    _video(path, "static")
    with pytest.raises(SceneCutAnalysisError, match="SCENE_CUT_ANALYSIS_LIMIT_EXCEEDED"):
        analyze_video(path, asset_id=1, asset_sha256="x", duration_seconds=121, source_fps="24/1", timeout_seconds=20)
