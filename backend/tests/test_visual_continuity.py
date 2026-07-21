from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw
import pytest
from sqlmodel import Session, select

from app.core.errors import AppError
from app.domain.visual_prompt_contract import (
    CameraLock,
    CharacterLock,
    EnvironmentLock,
    MotionDelta,
    StyleLock,
    VisualPromptContract,
)
from app.media.visual_continuity import (
    VisualContinuityConfig,
    camera_and_composition_status,
    classify_cut,
    compare_images,
    keyframe_delta_status,
    sample_times,
    stable_report_hash,
    style_drift_status,
)
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    HumanVisualStatus,
    ProductionGateStatus,
    Project,
    Shot,
    VisualAnalysisStatus,
    VisualContinuityReport,
)
from app.services.visual_continuity_service import production_gate, review_report


def _image(
    path: Path,
    *,
    box: tuple[int, int, int, int] = (35, 25, 95, 85),
    color: str = "red",
    texture: bool = False,
) -> None:
    image = Image.new("RGB", (128, 96), "#dddddd")
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, fill=color)
    if texture:
        for offset in range(0, 128, 4):
            draw.line((offset, 0, 127 - offset, 95), fill="#333333")
    image.save(path)


def _contract() -> VisualPromptContract:
    return VisualPromptContract(
        character=CharacterLock(
            identity_description="robot",
            shape="rounded",
            proportions="fixed",
            material="painted metal",
            colors=["red"],
            facial_features="black visor",
        ),
        camera=CameraLock(
            camera_position="front",
            camera_height="table",
            camera_angle="level",
            focal_length_style="normal",
            framing="wide",
            camera_motion_policy="FIXED",
        ),
        environment=EnvironmentLock(
            background="gray",
            surface="table",
            lighting="soft",
            shadow_direction="right",
            color_temperature="neutral",
        ),
        motion=MotionDelta(
            starting_pose="down",
            ending_pose="raised",
            allowed_motion="right arm",
            maximum_position_change="5%",
            maximum_scale_change="2%",
        ),
        style=StyleLock(
            rendering_style="3D toy photo",
            texture_style="smooth",
            detail_level="medium",
            realism_level="product photo",
        ),
    )


def test_config_and_report_hash_are_deterministic() -> None:
    config = VisualContinuityConfig()
    assert config.config_hash() == VisualContinuityConfig().config_hash()
    assert stable_report_hash({"b": 2, "a": 1}) == stable_report_hash({"a": 1, "b": 2})


def test_prompt_contract_is_stable_and_inherits_only_motion() -> None:
    contract = _contract()
    changed = contract.inherit_for_next_shot(
        contract.motion.model_copy(update={"ending_pose": "turned"})
    )
    assert contract.contract_hash() == _contract().contract_hash()
    assert changed.character == contract.character and changed.camera == contract.camera
    assert changed.environment == contract.environment and changed.style == contract.style
    assert changed.motion != contract.motion
    assert "FORBIDDEN" in contract.compile_prompt()


def test_prompt_contract_rejects_missing_production_lock() -> None:
    contract = _contract().model_copy(
        update={"camera": _contract().camera.model_copy(update={"framing": ""})}
    )
    with pytest.raises(AppError, match="locks are incomplete"):
        contract.validate_for_production()


def test_image_metrics_identical_compressed_and_changed(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    compressed = tmp_path / "compressed.jpg"
    shifted = tmp_path / "shifted.png"
    _image(original)
    Image.open(original).save(compressed, quality=92)
    _image(shifted, box=(5, 5, 55, 55), color="blue")
    same = compare_images(original, original)
    near = compare_images(original, compressed)
    far = compare_images(original, shifted)
    assert same.ssim == 1 and same.phash_distance == 0
    assert near.ssim > 0.95 and near.phash_distance <= 3
    assert far.ssim < near.ssim and (
        far.centroid_shift > 0.05 or far.salient_area_ratio_change > 0.1
    )


def test_keyframe_delta_states(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    c = tmp_path / "c.png"
    _image(a)
    _image(b, box=(38, 25, 98, 85))
    _image(c, box=(0, 0, 127, 95), color="blue", texture=True)
    assert keyframe_delta_status(compare_images(a, a)) == "TOO_SIMILAR"
    assert keyframe_delta_status(compare_images(a, b)) in {"ACCEPTABLE", "INCONCLUSIVE"}
    assert keyframe_delta_status(compare_images(a, c)) == "TOO_DIFFERENT"


def test_cut_style_camera_and_composition_gates(tmp_path: Path) -> None:
    flat = tmp_path / "flat.png"
    stable = tmp_path / "stable.png"
    jump = tmp_path / "jump.png"
    _image(flat)
    _image(stable, box=(36, 25, 96, 85))
    _image(jump, box=(0, 0, 127, 95), color="blue", texture=True)
    config = VisualContinuityConfig(scene_cut_confirmed_threshold=Decimal("0.20"))
    stable_metric = compare_images(flat, stable)
    jump_metric = compare_images(flat, jump)
    assert classify_cut(stable_metric, config) != "UNEXPECTED_HARD_CUT"
    assert classify_cut(jump_metric, config) in {"UNEXPECTED_HARD_CUT", "INCONCLUSIVE"}
    assert style_drift_status([stable_metric], config) in {"PASSED", "INCONCLUSIVE"}
    assert style_drift_status([jump_metric], config) in {"FAILED", "INCONCLUSIVE"}
    result = camera_and_composition_status(jump_metric, config)
    assert "FAILED" in {
        result["cameraStatus"],
        result["compositionStatus"],
        result["subjectScaleStatus"],
    }


def test_sampling_includes_endpoints_intervals_and_candidate_neighbors() -> None:
    values = sample_times(2.0, Decimal("0.5"), [1.0], fps=10)
    assert values[0] == 0 and 0.5 in values and 1.0 in values
    assert 0.9 in values and 1.1 in values and values[-1] == 1.9


@pytest.mark.parametrize(
    "technical,automatic,human,lineage,expected",
    [
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.PASSED,
            HumanVisualStatus.APPROVED,
            True,
            ProductionGateStatus.ALLOWED,
        ),
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.FAILED,
            HumanVisualStatus.APPROVED,
            True,
            ProductionGateStatus.BLOCKED,
        ),
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.INCONCLUSIVE,
            HumanVisualStatus.APPROVED,
            True,
            ProductionGateStatus.BLOCKED,
        ),
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.PASSED,
            HumanVisualStatus.PENDING,
            True,
            ProductionGateStatus.BLOCKED,
        ),
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.PASSED,
            HumanVisualStatus.REJECTED,
            True,
            ProductionGateStatus.BLOCKED,
        ),
        (
            VisualAnalysisStatus.PASSED,
            VisualAnalysisStatus.PASSED,
            HumanVisualStatus.APPROVED,
            False,
            ProductionGateStatus.BLOCKED,
        ),
    ],
)
def test_production_gate(
    technical: VisualAnalysisStatus,
    automatic: VisualAnalysisStatus,
    human: HumanVisualStatus,
    lineage: bool,
    expected: ProductionGateStatus,
) -> None:
    assert (
        production_gate(
            technical=technical, automatic=automatic, human=human, lineage_verified=lineage
        )
        == expected
    )


def test_report_identity_and_human_rejection_block(session: Session, tmp_path: Path) -> None:
    project = Project(name="visual")
    session.add(project)
    session.flush()
    shot = Shot(project_id=project.id or 0, title="shot")
    session.add(shot)
    session.flush()
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fixture")
    asset = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.VIDEO,
        status=AssetStatus.ACTIVE,
        path=str(path),
        mime_type="video/mp4",
    )
    session.add(asset)
    session.flush()
    report = VisualContinuityReport(
        project_id=project.id or 0,
        shot_id=shot.id,
        video_asset_id=asset.id or 0,
        analysis_version="visual-continuity-v1",
        config_hash="a" * 64,
        report_hash="b" * 64,
        technical_status=VisualAnalysisStatus.PASSED,
        automatic_visual_status=VisualAnalysisStatus.PASSED,
    )
    session.add(report)
    session.commit()
    rejected = review_report(
        session, report.id or 0, status=HumanVisualStatus.REJECTED, reasons=["STYLE"]
    )
    assert rejected.production_gate_status == ProductionGateStatus.BLOCKED
    assert rejected.overall_visual_status == VisualAnalysisStatus.FAILED
    assert len(session.exec(select(VisualContinuityReport)).all()) == 1
