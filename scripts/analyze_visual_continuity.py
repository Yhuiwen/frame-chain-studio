from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image, ImageDraw  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.media.visual_continuity import VisualContinuityConfig, sampled_frames, scene_candidates  # noqa: E402
from app.models.entities import Asset, HumanVisualStatus  # noqa: E402
from app.services.visual_continuity_service import (  # noqa: E402
    analyze_asset,
    analyze_cross_shot_seam,
    report_payload,
)

REASONS = [
    "CHARACTER_STYLE_DRIFT",
    "INTRA_SHOT_SCENE_CUT",
    "COMPOSITION_DISCONTINUITY",
    "SUBJECT_SCALE_DRIFT",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-asset-id", type=int)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--shot-id", type=int)
    parser.add_argument("--start-anchor-asset-id", type=int)
    parser.add_argument("--target-keyframe-asset-id", type=int)
    parser.add_argument("--tail-frame-asset-id", type=int)
    parser.add_argument("--analysis-version", default="visual-continuity-v1")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--generate-contact-sheet", action="store_true")
    parser.add_argument("--run6-calibration", action="store_true")
    args = parser.parse_args()
    if args.analysis_version != "visual-continuity-v1":
        raise SystemExit("VISUAL_ANALYSIS_VERSION_UNSUPPORTED")
    if args.run6_calibration:
        return run6(args.generate_contact_sheet)
    if not args.video_asset_id:
        raise SystemExit("VIDEO_ASSET_ID_REQUIRED")
    with Session(engine) as session:
        report = analyze_asset(
            session,
            video_asset_id=args.video_asset_id,
            start_anchor_asset_id=args.start_anchor_asset_id,
            target_keyframe_asset_id=args.target_keyframe_asset_id,
            tail_frame_asset_id=args.tail_frame_asset_id,
        )
        print(json.dumps(report_payload(report), ensure_ascii=False, default=str))
    return 0


def run6(generate_contact_sheet: bool) -> int:
    output = ROOT / ".run"
    output.mkdir(exist_ok=True)
    with Session(engine) as session:
        shot1 = analyze_asset(
            session,
            video_asset_id=86,
            start_anchor_asset_id=84,
            target_keyframe_asset_id=85,
            tail_frame_asset_id=87,
            human_status=HumanVisualStatus.REJECTED,
            human_rejection_reasons=REASONS,
        )
        shot2 = analyze_asset(
            session,
            video_asset_id=92,
            start_anchor_asset_id=90,
            target_keyframe_asset_id=91,
            tail_frame_asset_id=93,
            human_status=HumanVisualStatus.REJECTED,
            human_rejection_reasons=REASONS,
        )
        assets = {asset_id: session.get(Asset, asset_id) for asset_id in [87, 92, 94]}
        if any(asset is None for asset in assets.values()):
            raise SystemExit("RUN6_ASSET_MISSING")
        shot2_asset = assets[92]
        render = assets[94]
        tail = assets[87]
        assert shot2_asset is not None and render is not None and tail is not None
        config = VisualContinuityConfig()
        candidates = scene_candidates(Path(shot2_asset.path), config)
        with sampled_frames(Path(shot2_asset.path), [0.0]) as frames:
            first_copy = output / "run6-shot2-first-analysis.png"
            shutil.copy2(frames[0].path, first_copy)
        with sampled_frames(Path(render.path), [4.0, 4.083333]) as frames:
            before_copy = output / "run6-render-seam-before.png"
            after_copy = output / "run6-render-seam-after.png"
            shutil.copy2(frames[0].path, before_copy)
            shutil.copy2(frames[1].path, after_copy)
        seam = analyze_cross_shot_seam(
            tail_frame=Path(tail.path),
            next_first_frame=first_copy,
            render_before=before_copy,
            render_after=after_copy,
            lineage_verified=True,
            remote_last_frame_used=False,
        )
        shot_reports = [report_payload(shot1), report_payload(shot2)]
        automatic = (
            "FAILED"
            if any(report.automatic_visual_status == "FAILED" for report in (shot1, shot2))
            else "INCONCLUSIVE"
        )
        combined = {
            "analysisVersion": "visual-continuity-v1",
            "configHash": config.config_hash(),
            "technicalStatus": "PASSED",
            "automaticVisualStatus": automatic,
            "humanVisualStatus": "REJECTED",
            "productionQualityStatus": "FAILED",
            "productionGateStatus": "BLOCKED",
            "remoteLastFrameUsed": False,
            "lineageVerified": True,
            "rejectionReasons": REASONS,
            "shotReports": shot_reports,
            "crossShotSeam": seam,
        }
        (output / "run6-visual-continuity-v1-report.json").write_text(
            json.dumps(combined, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        cut_payload = {
            "shot1": shot_reports[0]["metrics"].get("sceneCutCandidates", []),
            "shot2": shot_reports[1]["metrics"].get("sceneCutCandidates", []),
        }
        (output / "run6-scene-cut-candidates.json").write_text(
            json.dumps(cut_payload, indent=2), encoding="utf-8"
        )
        (output / "run6-cross-shot-seam-report.json").write_text(
            json.dumps(seam, indent=2), encoding="utf-8"
        )
        if generate_contact_sheet:
            _contact_sheet(
                Path(render.path),
                output / "run6-visual-continuity-v1-contact-sheet.png",
                candidates,
            )
        first_copy.unlink(missing_ok=True)
        before_copy.unlink(missing_ok=True)
        after_copy.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "automaticVisualStatus": automatic,
                    "productionGateStatus": "BLOCKED",
                    "shot2Candidates": candidates,
                }
            )
        )
    return 0


def _contact_sheet(video: Path, output: Path, shot2_candidates: list[float]) -> None:
    render_candidates = [4.041667 + value for value in shot2_candidates]
    times = sorted(set([0.0, 2.0, 4.0, 4.083333, 6.083333, 8.0, *render_candidates]))
    with sampled_frames(video, times) as frames:
        tiles = []
        for frame in frames:
            with Image.open(frame.path) as source:
                image = source.convert("RGB")
                image.thumbnail((480, 270))
            tile = Image.new("RGB", (500, 310), "white")
            tile.paste(image, ((500 - image.width) // 2, 10))
            ImageDraw.Draw(tile).text(
                (10, 285), f"{frame.seconds:.6f}s / PTS {frame.pts}", fill="black"
            )
            tiles.append(tile)
        rows = (len(tiles) + 1) // 2
        sheet = Image.new("RGB", (1000, rows * 310), (230, 230, 230))
        for index, tile in enumerate(tiles):
            sheet.paste(tile, ((index % 2) * 500, (index // 2) * 310))
        sheet.save(output)


if __name__ == "__main__":
    raise SystemExit(main())
