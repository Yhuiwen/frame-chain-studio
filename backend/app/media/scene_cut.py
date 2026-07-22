from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from app.media.ffmpeg import require_binary


SCENE_CUT_ALGORITHM_VERSION = "scene-cut-v1"
CALIBRATION_SCOPE = "SYNTHETIC_FIXTURES_ONLY"


class SceneCutAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class SceneCutConfig:
    analysis_fps: int = 12
    width: int = 96
    height: int = 54
    pixel_format: str = "rgb24"
    histogram_bins: int = 16
    pixel_review_threshold: Decimal = Decimal("0.120000")
    pixel_hard_threshold: Decimal = Decimal("0.250000")
    histogram_review_threshold: Decimal = Decimal("0.200000")
    histogram_hard_threshold: Decimal = Decimal("0.450000")
    maximum_frames: int = 1440
    maximum_duration_seconds: Decimal = Decimal("120.000000")
    timestamp_places: int = 6
    classification_rule_id: str = "dual-metric-with-single-frame-return-v1"

    def snapshot(self, ffmpeg_major_version: str) -> dict[str, object]:
        return {
            "analysis_fps": str(self.analysis_fps),
            "analysis_width": self.width,
            "analysis_height": self.height,
            "pixel_format": self.pixel_format,
            "histogram_bins": self.histogram_bins,
            "pixel_review_threshold": _fixed(self.pixel_review_threshold),
            "pixel_hard_threshold": _fixed(self.pixel_hard_threshold),
            "histogram_review_threshold": _fixed(self.histogram_review_threshold),
            "histogram_hard_threshold": _fixed(self.histogram_hard_threshold),
            "maximum_frames": self.maximum_frames,
            "maximum_duration_seconds": _fixed(self.maximum_duration_seconds),
            "timestamp_rounding": f"decimal-{self.timestamp_places}-half-up",
            "ffmpeg_major_version": ffmpeg_major_version,
            "classification_rule_id": self.classification_rule_id,
        }


@dataclass(frozen=True)
class FrameSample:
    sample_index: int
    timestamp_seconds: str
    frame_sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class SceneCutEvent:
    boundary_index: int
    timestamp_seconds: str
    previous_timestamp_seconds: str
    pixel_delta: str
    histogram_delta: str
    classification: str
    blocking: bool
    previous_frame_sha256: str
    frame_sha256: str


@dataclass(frozen=True)
class SceneCutResult:
    asset_id: int
    asset_sha256: str
    algorithm_version: str
    duration_seconds: str
    source_fps: str
    analysis_fps: str
    frame_count: int
    parameters: dict[str, object]
    samples: tuple[FrameSample, ...]
    events: tuple[SceneCutEvent, ...]
    hard_cut_count: int
    review_candidate_count: int
    maximum_pixel_delta: str
    maximum_histogram_delta: str
    calibration_scope: str = CALIBRATION_SCOPE

    def manifest(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "asset_sha256": self.asset_sha256,
            "algorithm_version": self.algorithm_version,
            "duration_seconds": self.duration_seconds,
            "source_fps": self.source_fps,
            "analysis_fps": self.analysis_fps,
            "frame_count": self.frame_count,
            "samples": [asdict(sample) for sample in self.samples],
        }

    def evidence(self) -> dict[str, object]:
        manifest = self.manifest()
        timestamps = [sample.timestamp_seconds for sample in self.samples]
        persisted_events = self.events[:8]
        return {
            "asset_id": self.asset_id,
            "asset_sha256": self.asset_sha256,
            "algorithm_version": self.algorithm_version,
            "parameters": self.parameters,
            "sample_manifest": {
                "frame_count": self.frame_count,
                "timestamps_sha256": _json_hash(timestamps),
                "manifest_sha256": _json_hash(manifest),
            },
            "events": [asdict(event) for event in persisted_events],
            "events_truncated": len(self.events) > len(persisted_events),
            "hard_cut_count": self.hard_cut_count,
            "review_candidate_count": self.review_candidate_count,
            "maximum_pixel_delta": self.maximum_pixel_delta,
            "maximum_histogram_delta": self.maximum_histogram_delta,
            "calibration_scope": self.calibration_scope,
        }


def analyze_video(
    path: Path,
    *,
    asset_id: int,
    asset_sha256: str,
    duration_seconds: float,
    source_fps: str,
    timeout_seconds: int,
    config: SceneCutConfig = SceneCutConfig(),
) -> SceneCutResult:
    duration = Decimal(str(duration_seconds)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if duration <= 0 or duration > config.maximum_duration_seconds:
        raise SceneCutAnalysisError("SCENE_CUT_ANALYSIS_LIMIT_EXCEEDED")
    expected_max = int((duration * config.analysis_fps).to_integral_value(rounding=ROUND_HALF_UP)) + 1
    if expected_max > config.maximum_frames:
        raise SceneCutAnalysisError("SCENE_CUT_ANALYSIS_LIMIT_EXCEEDED")
    if not path.is_file():
        raise SceneCutAnalysisError("SCENE_CUT_VIDEO_MISSING")
    frame_size = config.width * config.height * 3
    command = [
        require_binary("ffmpeg"), "-v", "error", "-i", str(path), "-an", "-vf",
        f"fps={config.analysis_fps},scale={config.width}:{config.height}:flags=neighbor",
        "-pix_fmt", config.pixel_format, "-f", "rawvideo", "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SceneCutAnalysisError("SCENE_CUT_FFMPEG_TIMEOUT") from exc
    if completed.returncode != 0:
        raise SceneCutAnalysisError("SCENE_CUT_DECODE_FAILED")
    if len(completed.stdout) % frame_size:
        raise SceneCutAnalysisError("SCENE_CUT_FRAME_SIZE_MISMATCH")
    frames = [completed.stdout[index:index + frame_size] for index in range(0, len(completed.stdout), frame_size)]
    if not frames:
        raise SceneCutAnalysisError("SCENE_CUT_NO_FRAMES")
    if len(frames) > config.maximum_frames:
        raise SceneCutAnalysisError("SCENE_CUT_ANALYSIS_LIMIT_EXCEEDED")
    ffmpeg_major = _ffmpeg_major_version(timeout_seconds)
    parameters = config.snapshot(ffmpeg_major)
    samples = tuple(
        FrameSample(
            sample_index=index,
            timestamp_seconds=_timestamp(index, config.analysis_fps),
            frame_sha256=sha256(frame).hexdigest(),
            width=config.width,
            height=config.height,
        )
        for index, frame in enumerate(frames)
    )
    metrics = [_frame_metrics(frames[index - 1], frames[index], config) for index in range(1, len(frames))]
    classifications = [_classification(pixel, histogram, config) for pixel, histogram in metrics]
    for index in range(len(classifications) - 1):
        if classifications[index] != "HARD_CUT" or classifications[index + 1] != "HARD_CUT":
            continue
        return_pixel, return_histogram = _frame_metrics(frames[index], frames[index + 2], config)
        if return_pixel < config.pixel_review_threshold and return_histogram < config.histogram_review_threshold:
            classifications[index] = "REVIEW_CANDIDATE"
            classifications[index + 1] = "REVIEW_CANDIDATE"
    events = tuple(
        SceneCutEvent(
            boundary_index=index + 1,
            timestamp_seconds=samples[index + 1].timestamp_seconds,
            previous_timestamp_seconds=samples[index].timestamp_seconds,
            pixel_delta=_fixed(metrics[index][0]),
            histogram_delta=_fixed(metrics[index][1]),
            classification=classification,
            blocking=classification == "HARD_CUT",
            previous_frame_sha256=samples[index].frame_sha256,
            frame_sha256=samples[index + 1].frame_sha256,
        )
        for index, classification in enumerate(classifications)
        if classification != "NONE"
    )
    return SceneCutResult(
        asset_id=asset_id,
        asset_sha256=asset_sha256,
        algorithm_version=SCENE_CUT_ALGORITHM_VERSION,
        duration_seconds=_fixed(duration),
        source_fps=source_fps,
        analysis_fps=str(config.analysis_fps),
        frame_count=len(samples),
        parameters=parameters,
        samples=samples,
        events=events,
        hard_cut_count=sum(event.classification == "HARD_CUT" for event in events),
        review_candidate_count=sum(event.classification == "REVIEW_CANDIDATE" for event in events),
        maximum_pixel_delta=_fixed(max((item[0] for item in metrics), default=Decimal(0))),
        maximum_histogram_delta=_fixed(max((item[1] for item in metrics), default=Decimal(0))),
    )


def _frame_metrics(left: bytes, right: bytes, config: SceneCutConfig) -> tuple[Decimal, Decimal]:
    if len(left) != len(right) or not left:
        raise SceneCutAnalysisError("SCENE_CUT_FRAME_SIZE_MISMATCH")
    pixel = Decimal(sum(abs(a - b) for a, b in zip(left, right, strict=True))) / Decimal(len(left) * 255)
    bins = config.histogram_bins
    hist_left = [[0] * bins for _ in range(3)]
    hist_right = [[0] * bins for _ in range(3)]
    for index in range(0, len(left), 3):
        for channel in range(3):
            hist_left[channel][min(bins - 1, left[index + channel] * bins // 256)] += 1
            hist_right[channel][min(bins - 1, right[index + channel] * bins // 256)] += 1
    pixels = len(left) // 3
    histogram = Decimal(
        sum(
            abs(a - b)
            for left_channel, right_channel in zip(hist_left, hist_right, strict=True)
            for a, b in zip(left_channel, right_channel, strict=True)
        )
    ) / Decimal(6 * pixels)
    return pixel, histogram


def _classification(pixel: Decimal, histogram: Decimal, config: SceneCutConfig) -> str:
    if pixel >= config.pixel_hard_threshold and histogram >= config.histogram_hard_threshold:
        return "HARD_CUT"
    if pixel >= config.pixel_review_threshold and histogram >= config.histogram_review_threshold:
        return "REVIEW_CANDIDATE"
    return "NONE"


def _timestamp(index: int, fps: int) -> str:
    return _fixed(Decimal(index) / Decimal(fps))


def _fixed(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def _json_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _ffmpeg_major_version(timeout_seconds: int) -> str:
    completed = subprocess.run(
        [require_binary("ffmpeg"), "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout_seconds, check=False, shell=False,
    )
    first = completed.stdout.decode("utf-8", errors="replace").splitlines()[0]
    version = first.split("version", 1)[-1].strip().split(".", 1)[0].split("-", 1)[0]
    return version or "unknown"
