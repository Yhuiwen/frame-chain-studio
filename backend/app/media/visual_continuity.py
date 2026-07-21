from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app.media.ffmpeg import require_binary

ANALYSIS_VERSION = "visual-continuity-v1"


@dataclass(frozen=True)
class VisualContinuityConfig:
    sample_interval_seconds: Decimal = Decimal("0.5")
    scene_cut_candidate_threshold: Decimal = Decimal("0.08")
    scene_cut_confirmed_threshold: Decimal = Decimal("0.30")
    histogram_delta_threshold: Decimal = Decimal("0.22")
    edge_delta_threshold: Decimal = Decimal("0.18")
    anchor_ssim_threshold: Decimal = Decimal("0.72")
    anchor_phash_distance_threshold: int = 18
    target_ssim_threshold: Decimal = Decimal("0.62")
    target_phash_distance_threshold: int = 24
    cross_shot_ssim_threshold: Decimal = Decimal("0.82")
    cross_shot_phash_distance_threshold: int = 12
    camera_translation_threshold: Decimal = Decimal("0.10")
    camera_scale_threshold: Decimal = Decimal("0.30")
    camera_rotation_threshold: Decimal = Decimal("5")
    composition_centroid_threshold: Decimal = Decimal("0.16")
    composition_area_ratio_threshold: Decimal = Decimal("0.35")
    subject_scale_change_threshold: Decimal = Decimal("0.40")
    style_histogram_threshold: Decimal = Decimal("0.28")
    style_edge_density_threshold: Decimal = Decimal("0.12")
    minimum_feature_matches: int = 24
    uncertain_result_policy: str = "BLOCK"

    def stable_dict(self) -> dict[str, str | int]:
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }

    def config_hash(self) -> str:
        payload = json.dumps(self.stable_dict(), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class FrameMetric:
    ssim: float
    phash_distance: int
    histogram_delta: float
    edge_delta: float
    brightness_delta: float
    centroid_shift: float
    salient_area_ratio_change: float
    reference_aspect_ratio: float
    actual_aspect_ratio: float


@dataclass(frozen=True)
class SampledFrame:
    seconds: float
    pts: int
    path: Path


def stable_report_hash(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def compare_images(
    reference_path: Path, actual_path: Path, *, size: tuple[int, int] = (256, 144)
) -> FrameMetric:
    with Image.open(reference_path) as left_raw, Image.open(actual_path) as right_raw:
        left_aspect = left_raw.width / left_raw.height
        right_aspect = right_raw.width / right_raw.height
        left = _contain(left_raw.convert("RGB"), size)
        right = _contain(right_raw.convert("RGB"), size)
    left_gray = left.convert("L")
    right_gray = right.convert("L")
    return FrameMetric(
        ssim=round(_global_ssim(left_gray, right_gray), 6),
        phash_distance=_hamming(_dhash(left_gray), _dhash(right_gray)),
        histogram_delta=round(_histogram_delta(left, right), 6),
        edge_delta=round(abs(_edge_density(left_gray) - _edge_density(right_gray)), 6),
        brightness_delta=round(
            abs(ImageStat.Stat(left_gray).mean[0] - ImageStat.Stat(right_gray).mean[0]) / 255, 6
        ),
        centroid_shift=round(_centroid_shift(left_gray, right_gray), 6),
        salient_area_ratio_change=round(_salient_area_change(left_gray, right_gray), 6),
        reference_aspect_ratio=round(left_aspect, 6),
        actual_aspect_ratio=round(right_aspect, 6),
    )


def match_status(metric: FrameMetric, *, ssim_threshold: Decimal, phash_threshold: int) -> str:
    if metric.ssim >= float(ssim_threshold) and metric.phash_distance <= phash_threshold:
        return "PASSED"
    if metric.ssim < float(ssim_threshold) * 0.75 and metric.phash_distance > phash_threshold:
        return "FAILED"
    return "INCONCLUSIVE"


def keyframe_delta_status(metric: FrameMetric) -> str:
    if metric.ssim > 0.97 and metric.phash_distance <= 2:
        return "TOO_SIMILAR"
    if (
        metric.ssim < 0.35
        or metric.centroid_shift > 0.30
        or metric.salient_area_ratio_change > 0.60
    ):
        return "TOO_DIFFERENT"
    if metric.ssim >= 0.55 and metric.phash_distance <= 30:
        return "ACCEPTABLE"
    return "INCONCLUSIVE"


def scene_candidates(
    video_path: Path, config: VisualContinuityConfig, *, timeout_seconds: int = 60
) -> list[float]:
    expression = f"select='gt(scene,{config.scene_cut_candidate_threshold})',showinfo"
    completed = subprocess.run(
        [
            require_binary("ffmpeg"),
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            expression,
            "-an",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("FFmpeg scene analysis failed.")
    text = completed.stderr.decode("utf-8", errors="replace")
    return sorted({round(float(value), 6) for value in re.findall(r"pts_time:([0-9.]+)", text)})


def sample_times(
    duration: float, interval: Decimal, candidates: list[float] | None = None, *, fps: float = 24
) -> list[float]:
    step = float(interval)
    values = {0.0, max(0.0, duration / 2), max(0.0, duration - 1 / fps)}
    current = step
    while current < duration:
        values.add(round(current, 6))
        current += step
    for candidate in candidates or []:
        values.add(max(0.0, round(candidate - 1 / fps, 6)))
        values.add(min(max(0.0, duration - 1 / fps), round(candidate + 1 / fps, 6)))
    return sorted(values)


@contextmanager
def sampled_frames(
    video_path: Path, times: list[float], *, fps: float = 24, timeout_seconds: int = 60
) -> Iterator[list[SampledFrame]]:
    with TemporaryDirectory(prefix="visual-continuity-") as directory:
        root = Path(directory)
        frames: list[SampledFrame] = []
        for index, seconds in enumerate(times):
            output = root / f"frame-{index:04d}.png"
            completed = subprocess.run(
                [
                    require_binary("ffmpeg"),
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    f"{seconds:.6f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
            if completed.returncode != 0 or not output.exists():
                raise RuntimeError("FFmpeg frame extraction failed.")
            frames.append(SampledFrame(seconds=seconds, pts=round(seconds * fps), path=output))
        yield frames


def classify_cut(metric: FrameMetric, config: VisualContinuityConfig) -> str:
    strong = metric.histogram_delta >= float(config.histogram_delta_threshold) and (
        metric.ssim <= 1 - float(config.scene_cut_confirmed_threshold)
        or metric.centroid_shift >= float(config.composition_centroid_threshold)
        or metric.salient_area_ratio_change >= float(config.composition_area_ratio_threshold)
    )
    if strong and (
        metric.phash_distance >= 16 or metric.edge_delta >= float(config.edge_delta_threshold)
    ):
        return "UNEXPECTED_HARD_CUT"
    if metric.ssim < 0.72 or metric.histogram_delta >= float(config.histogram_delta_threshold):
        return "INCONCLUSIVE"
    return "NO_HARD_CUT"


def style_drift_status(
    metrics_from_first: list[FrameMetric], config: VisualContinuityConfig
) -> str:
    if not metrics_from_first:
        return "INCONCLUSIVE"
    severe = [
        m
        for m in metrics_from_first
        if m.histogram_delta >= float(config.style_histogram_threshold)
        and m.edge_delta >= float(config.style_edge_density_threshold)
    ]
    if severe:
        return "FAILED"
    if (
        max(m.histogram_delta for m in metrics_from_first)
        > float(config.style_histogram_threshold) * 0.75
    ):
        return "INCONCLUSIVE"
    return "PASSED"


def camera_and_composition_status(
    metric: FrameMetric, config: VisualContinuityConfig, *, camera_policy: str = "FIXED"
) -> dict[str, object]:
    proxy_features = round(_proxy_feature_count(metric))
    confidence = min(1.0, proxy_features / max(1, config.minimum_feature_matches * 2))
    camera = "INCONCLUSIVE" if proxy_features < config.minimum_feature_matches else "PASSED"
    if camera_policy == "FIXED" and (
        metric.centroid_shift > float(config.camera_translation_threshold)
        or metric.salient_area_ratio_change > float(config.camera_scale_threshold)
    ):
        camera = "FAILED"
    composition = (
        "FAILED"
        if metric.centroid_shift > float(config.composition_centroid_threshold)
        else "PASSED"
    )
    scale = (
        "FAILED"
        if metric.salient_area_ratio_change > float(config.subject_scale_change_threshold)
        else "PASSED"
    )
    return {
        "cameraStatus": camera,
        "compositionStatus": composition,
        "subjectScaleStatus": scale,
        "translationRatio": metric.centroid_shift,
        "translationPixels": round(metric.centroid_shift * 256, 3),
        "scaleFactorProxy": round(1 + metric.salient_area_ratio_change, 6),
        "rotationDegrees": None,
        "featureMatchCountProxy": proxy_features,
        "inlierCount": None,
        "confidence": round(confidence, 6),
    }


def _contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    contained = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
    background = tuple(round(value) for value in ImageStat.Stat(contained).mean[:3])
    canvas = Image.new("RGB", size, background)
    canvas.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
    return canvas


def _global_ssim(left: Image.Image, right: Image.Image) -> float:
    left_values = list(left.getdata())
    right_values = list(right.getdata())
    left_mean = sum(left_values) / len(left_values)
    right_mean = sum(right_values) / len(right_values)
    left_var = sum((v - left_mean) ** 2 for v in left_values) / len(left_values)
    right_var = sum((v - right_mean) ** 2 for v in right_values) / len(right_values)
    covariance = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left_values, right_values, strict=True)
    ) / len(left_values)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return max(
        0.0,
        min(
            1.0,
            ((2 * left_mean * right_mean + c1) * (2 * covariance + c2))
            / ((left_mean**2 + right_mean**2 + c1) * (left_var + right_var + c2)),
        ),
    )


def _dhash(image: Image.Image) -> int:
    pixels = list(image.resize((9, 8)).getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _histogram_delta(left: Image.Image, right: Image.Image) -> float:
    left_hist = left.resize((64, 64)).histogram()
    right_hist = right.resize((64, 64)).histogram()
    total = sum(left_hist)
    return sum(abs(a - b) for a, b in zip(left_hist, right_hist, strict=True)) / (2 * total)


def _edge_density(image: Image.Image) -> float:
    edges = image.filter(ImageFilter.FIND_EDGES)
    get_pixels = getattr(edges, "get_flattened_data", edges.getdata)
    pixels = list(get_pixels())  # type: ignore[union-attr]
    return sum(value > 32 for value in pixels) / (edges.width * edges.height)


def _edge_proxy(image: Image.Image) -> tuple[float, float, float]:
    edges = image.filter(ImageFilter.FIND_EDGES)
    points = []
    for index, value in enumerate(edges.getdata()):
        if value > 48:
            points.append((index % edges.width, index // edges.width))
    if not points:
        return (0.5, 0.5, 0.0)
    return (
        sum(x for x, _ in points) / len(points) / edges.width,
        sum(y for _, y in points) / len(points) / edges.height,
        len(points) / (edges.width * edges.height),
    )


def _centroid_shift(left: Image.Image, right: Image.Image) -> float:
    lx, ly, _ = _edge_proxy(left)
    rx, ry, _ = _edge_proxy(right)
    return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5


def _salient_area_change(left: Image.Image, right: Image.Image) -> float:
    *_, left_area = _edge_proxy(left)
    *_, right_area = _edge_proxy(right)
    return abs(left_area - right_area) / max(left_area, right_area, 0.001)


def _proxy_feature_count(metric: FrameMetric) -> float:
    return max(0.0, (1 - metric.edge_delta) * 64)
