from __future__ import annotations

import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.models.entities import Asset, ProviderVerificationRun  # noqa: E402
from app.services.toapis_recovery_planning import repair_historical_anchor_failure_evidence  # noqa: E402
from app.services.video_input_normalization import normalize_video_input_frame  # noqa: E402


def main() -> int:
    repair_historical_anchor_failure_evidence_session()
    with Session(engine) as session:
        run = session.get(ProviderVerificationRun, 5)
        if run is None or run.initial_anchor_asset_id is None:
            raise RuntimeError("Run 5 anchor is missing")
        start = session.get(Asset, run.initial_anchor_asset_id)
        end = session.get(Asset, 83)
        if start is None or end is None:
            raise RuntimeError("Run 5 source assets are missing")
        normalized_start = normalize_video_input_frame(session, source_asset_id=start.id or 0, frame_role="START")
        normalized_end = normalize_video_input_frame(session, source_asset_id=end.id or 0, frame_role="END")
        sources = [start, normalized_start.asset, end, normalized_end.asset]
        labels = ["Original START", "Normalized START", "Original END (Asset 83)", "Normalized END"]
        evidence = [normalized_start.evidence, normalized_end.evidence]
        summary = {
            "normalizationVersion": "video-input-v1",
            "humanReviewStatus": "PENDING",
            "cropApplied": False,
            "stretchApplied": False,
            "frames": [
                {
                    "frameRole": item.frame_role,
                    "sourceAssetId": item.source_asset_id,
                    "normalizedAssetId": item.normalized_asset_id,
                    "sourceSize": [source.width, source.height],
                    "normalizedSize": [normalized.width, normalized.height],
                    "sourceSha256": item.source_sha256,
                    "normalizedSha256": item.normalized_sha256,
                    "padding": {
                        "left": item.padding_left,
                        "right": item.padding_right,
                        "top": item.padding_top,
                        "bottom": item.padding_bottom,
                        "color": item.padding_color,
                    },
                    "cropApplied": item.crop_applied,
                    "stretchApplied": False,
                }
                for item, source, normalized in zip(evidence, (start, end), (normalized_start.asset, normalized_end.asset), strict=True)
            ],
        }
        paths = [Path(asset.path) for asset in sources]
    _contact_sheet(paths, labels, ROOT / ".run" / "run5-anchor-normalization-contact-sheet.png")
    (ROOT / ".run" / "run5-anchor-normalization-review.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for frame in summary["frames"]:
        print(
            f"{frame['frameRole'].lower()}NormalizedAssetId={frame['normalizedAssetId']} "
            f"size={frame['normalizedSize'][0]}x{frame['normalizedSize'][1]} "
            f"sha256={frame['normalizedSha256']} padding={frame['padding']}"
        )
    print("humanReviewStatus=PENDING")
    return 0


def repair_historical_anchor_failure_evidence_session() -> None:
    with Session(engine) as session:
        repair_historical_anchor_failure_evidence(session, failed_run_id=5)


def _contact_sheet(paths: list[Path], labels: list[str], output: Path) -> None:
    cell_width, cell_height, label_height = 640, 360, 32
    sheet = Image.new("RGB", (cell_width * 2, (cell_height + label_height) * 2), "#202020")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (path, label) in enumerate(zip(paths, labels, strict=True)):
        with Image.open(path) as opened:
            image = ImageOps.contain(ImageOps.exif_transpose(opened).convert("RGB"), (cell_width, cell_height))
        x = (index % 2) * cell_width
        y = (index // 2) * (cell_height + label_height)
        left = x + (cell_width - image.width) // 2
        top = y + label_height + (cell_height - image.height) // 2
        sheet.paste(image, (left, top))
        draw.text((x + 8, y + 8), label, fill="white", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=False, compress_level=9)


if __name__ == "__main__":
    raise SystemExit(main())
