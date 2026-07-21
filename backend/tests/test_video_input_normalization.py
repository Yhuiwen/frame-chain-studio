from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image
from sqlmodel import Session, select

from app.models.entities import Asset, AssetType, Project, Shot, VideoInputFrameNormalization
from app.services.video_input_normalization import _normalized_png, normalize_video_input_frame


def _image(path: Path, size: tuple[int, int], *, mode: str = "RGB", exif_orientation: int | None = None) -> None:
    color = (30, 80, 140, 120) if mode == "RGBA" else (30, 80, 140)
    image = Image.new(mode, size, color)
    image.putpixel((size[0] - 1, size[1] - 1), color)
    exif = Image.Exif()
    if exif_orientation is not None:
        exif[274] = exif_orientation
    image.save(path, format="PNG", exif=exif, icc_profile=b"test-profile")


def _dimensions(payload: bytes) -> tuple[tuple[int, int], str, dict[Any, Any]]:
    with Image.open(BytesIO(payload)) as image:
        image.load()
        return image.size, image.mode, cast(dict[Any, Any], image.info)


def _asset(session: Session, tmp_path: Path, size: tuple[int, int] = (2848, 1600)) -> Asset:
    project = Project(name="normalization")
    session.add(project)
    session.flush()
    shot = Shot(project_id=project.id or 0, title="shot", duration_seconds=4, prompt="", sort_order=0)
    session.add(shot)
    session.flush()
    path = tmp_path / "source.png"
    _image(path, size)
    payload = path.read_bytes()
    asset = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        revision=1,
        path=str(path),
        mime_type="image/png",
        sha256=sha256(payload).hexdigest(),
        file_size=len(payload),
        width=size[0],
        height=size[1],
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def test_2848x1600_normalizes_with_one_pixel_padding(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (2848, 1600))
    payload, padding, _ = _normalized_png(source)
    assert _dimensions(payload)[:2] == ((1280, 720), "RGB")
    assert sum(padding) == 1


def test_identity_normalization_is_exact_and_unpadded(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (1280, 720))
    payload, padding, _ = _normalized_png(source)
    assert _dimensions(payload)[:2] == ((1280, 720), "RGB")
    assert padding == (0, 0, 0, 0)


def test_contain_does_not_crop_or_stretch(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (800, 800))
    _, padding, _ = _normalized_png(source)
    assert padding == (280, 280, 0, 0)


def test_small_aspect_difference_is_padded(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (1279, 720))
    _, padding, _ = _normalized_png(source)
    assert sum(padding) == 1


def test_exif_orientation_is_applied(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (720, 1280), exif_orientation=6)
    _, padding, _ = _normalized_png(source)
    assert padding == (0, 0, 0, 0)


def test_alpha_and_metadata_are_removed(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (1280, 720), mode="RGBA")
    payload, _, _ = _normalized_png(source)
    size, mode, info = _dimensions(payload)
    assert size == (1280, 720)
    assert mode == "RGB"
    assert info == {}
    assert len(payload) < 10 * 1024 * 1024


def test_normalized_sha_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _image(source, (2848, 1600))
    first, _, _ = _normalized_png(source)
    second, _, _ = _normalized_png(source)
    assert sha256(first).hexdigest() == sha256(second).hexdigest()


def test_normalization_asset_is_idempotent(session: Session, tmp_path: Path) -> None:
    source = _asset(session, tmp_path)
    first = normalize_video_input_frame(session, source_asset_id=source.id or 0, frame_role="END")
    second = normalize_video_input_frame(session, source_asset_id=source.id or 0, frame_role="END")
    assert first.asset.id == second.asset.id
    assert first.asset.source_asset_id == source.id
    assert first.asset.type == AssetType.VIDEO_INPUT_FRAME
    assert first.asset.width == 1280 and first.asset.height == 720
    assert first.asset.mime_type == "image/png"
    records = session.exec(select(VideoInputFrameNormalization)).all()
    assert len(records) == 1
    assert records[0].frame_role == "END"
    assert records[0].crop_applied is False
