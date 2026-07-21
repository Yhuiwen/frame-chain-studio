from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from statistics import median

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    VideoInputFrameNormalization,
)

NORMALIZATION_VERSION = "video-input-v1"
TARGET_WIDTH = 1280
TARGET_HEIGHT = 720
MAX_OUTPUT_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class NormalizedFrameResult:
    asset: Asset
    evidence: VideoInputFrameNormalization


def normalize_video_input_frame(
    session: Session,
    *,
    source_asset_id: int,
    frame_role: str,
) -> NormalizedFrameResult:
    role = frame_role.upper()
    if role not in {"START", "END"}:
        raise AppError("VIDEO_FRAME_ROLE_INVALID", "Frame role must be START or END.", 409)
    existing = session.exec(
        select(VideoInputFrameNormalization).where(
            VideoInputFrameNormalization.source_asset_id == source_asset_id,
            VideoInputFrameNormalization.normalization_version == NORMALIZATION_VERSION,
            VideoInputFrameNormalization.target_width == TARGET_WIDTH,
            VideoInputFrameNormalization.target_height == TARGET_HEIGHT,
        )
    ).first()
    if existing is not None:
        if existing.frame_role != role:
            raise AppError("VIDEO_FRAME_ROLE_CONFLICT", "The normalized source already has another frame role.", 409)
        asset = session.get(Asset, existing.normalized_asset_id)
        if asset is None or not _valid_normalized_asset(asset, existing):
            raise AppError("NORMALIZED_VIDEO_FRAME_INVALID", "The existing normalized frame is invalid.", 409)
        return NormalizedFrameResult(asset=asset, evidence=existing)

    source = session.get(Asset, source_asset_id)
    if source is None:
        raise AppError("SOURCE_VIDEO_FRAME_INVALID", "The source frame asset is invalid.", 409)
    source_path = Path(source.path)
    if not source_path.is_file():
        raise AppError("SOURCE_VIDEO_FRAME_INVALID", "The source frame file failed integrity validation.", 409)
    source_sha = _file_sha256(source_path)
    if source.sha256 and source_sha != source.sha256:
        raise AppError("SOURCE_VIDEO_FRAME_INVALID", "The source frame file failed integrity validation.", 409)
    project_id, shot_id, revision = source.project_id, source.shot_id, source.revision
    session.commit()

    normalized_bytes, padding, padding_color = _normalized_png(source_path)
    normalized_sha = sha256(normalized_bytes).hexdigest()
    output_dir = get_settings().storage_dir / "projects" / str(project_id) / "video-input-frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_asset_id}-{NORMALIZATION_VERSION}-{normalized_sha[:16]}.png"
    if not output_path.exists():
        part_path = output_path.with_suffix(".png.part")
        part_path.write_bytes(normalized_bytes)
        part_path.replace(output_path)
    if output_path.stat().st_size > MAX_OUTPUT_BYTES or _file_sha256(output_path) != normalized_sha:
        raise AppError("NORMALIZED_VIDEO_FRAME_INVALID", "The normalized frame failed integrity validation.", 409)

    asset = Asset(
        project_id=project_id,
        shot_id=shot_id,
        type=AssetType.VIDEO_INPUT_FRAME,
        status=AssetStatus.ACTIVE,
        revision=revision,
        path=str(output_path),
        mime_type="image/png",
        source_asset_id=source_asset_id,
        sha256=normalized_sha,
        file_size=len(normalized_bytes),
        width=TARGET_WIDTH,
        height=TARGET_HEIGHT,
    )
    session.add(asset)
    try:
        session.flush()
        evidence = VideoInputFrameNormalization(
            source_asset_id=source_asset_id,
            normalized_asset_id=asset.id or 0,
            frame_role=role,
            padding_applied=any(padding),
            padding_left=padding[0],
            padding_right=padding[1],
            padding_top=padding[2],
            padding_bottom=padding[3],
            padding_color=",".join(str(value) for value in padding_color),
            source_sha256=source_sha,
            normalized_sha256=normalized_sha,
        )
        session.add(evidence)
        session.commit()
        session.refresh(asset)
        session.refresh(evidence)
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(VideoInputFrameNormalization).where(
                VideoInputFrameNormalization.source_asset_id == source_asset_id,
                VideoInputFrameNormalization.normalization_version == NORMALIZATION_VERSION,
                VideoInputFrameNormalization.target_width == TARGET_WIDTH,
                VideoInputFrameNormalization.target_height == TARGET_HEIGHT,
            )
        ).one()
        existing_asset = session.get(Asset, existing.normalized_asset_id)
        if existing_asset is None:
            raise AppError("NORMALIZED_VIDEO_FRAME_INVALID", "Concurrent normalization failed.", 409)
        return NormalizedFrameResult(asset=existing_asset, evidence=existing)
    return NormalizedFrameResult(asset=asset, evidence=evidence)


def _normalized_png(source_path: Path) -> tuple[bytes, tuple[int, int, int, int], tuple[int, int, int]]:
    try:
        with Image.open(source_path) as opened:
            oriented = ImageOps.exif_transpose(opened)
            rgb = oriented.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError("SOURCE_VIDEO_FRAME_INVALID", "The source frame is not a valid image.", 409) from exc
    corners: list[tuple[int, int, int]] = []
    for point in ((0, 0), (rgb.width - 1, 0), (0, rgb.height - 1), (rgb.width - 1, rgb.height - 1)):
        pixel = rgb.getpixel(point)
        if not isinstance(pixel, tuple) or len(pixel) < 3:
            raise AppError("SOURCE_VIDEO_FRAME_INVALID", "The source frame pixel mode is invalid.", 409)
        corners.append((int(pixel[0]), int(pixel[1]), int(pixel[2])))
    padding_color: tuple[int, int, int] = (
        int(median(pixel[0] for pixel in corners)),
        int(median(pixel[1] for pixel in corners)),
        int(median(pixel[2] for pixel in corners)),
    )
    scale = min(TARGET_WIDTH / rgb.width, TARGET_HEIGHT / rgb.height)
    width = max(1, min(TARGET_WIDTH, round(rgb.width * scale)))
    height = max(1, min(TARGET_HEIGHT, round(rgb.height * scale)))
    resized = rgb.resize((width, height), Image.Resampling.LANCZOS)
    left = (TARGET_WIDTH - width) // 2
    top = (TARGET_HEIGHT - height) // 2
    right = TARGET_WIDTH - width - left
    bottom = TARGET_HEIGHT - height - top
    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), padding_color)
    canvas.paste(resized, (left, top))
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=False, compress_level=9)
    payload = output.getvalue()
    if len(payload) > MAX_OUTPUT_BYTES:
        raise AppError("NORMALIZED_VIDEO_FRAME_TOO_LARGE", "The normalized frame exceeds 10 MB.", 409)
    with Image.open(BytesIO(payload)) as verified:
        verified.load()
        if verified.mode != "RGB" or verified.size != (TARGET_WIDTH, TARGET_HEIGHT) or verified.info:
            raise AppError("NORMALIZED_VIDEO_FRAME_INVALID", "The normalized frame metadata is invalid.", 409)
    return payload, (left, right, top, bottom), padding_color


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_normalized_asset(asset: Asset, evidence: VideoInputFrameNormalization) -> bool:
    path = Path(asset.path)
    return bool(
        asset.type == AssetType.VIDEO_INPUT_FRAME
        and asset.source_asset_id == evidence.source_asset_id
        and asset.width == TARGET_WIDTH
        and asset.height == TARGET_HEIGHT
        and asset.mime_type == "image/png"
        and asset.file_size is not None
        and asset.file_size <= MAX_OUTPUT_BYTES
        and asset.sha256 == evidence.normalized_sha256
        and path.is_file()
        and _file_sha256(path) == evidence.normalized_sha256
    )
