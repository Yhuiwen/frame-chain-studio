from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "data" / "frame_chain.db"
OUTPUT = ROOT / ".run"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    with sqlite3.connect(DB) as connection:
        row = connection.execute("SELECT path FROM asset WHERE id=76").fetchone()
    if not row:
        raise RuntimeError("ASSET_76_NOT_FOUND")
    source = Path(row[0])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    start_path = OUTPUT / "toapis-video-canary-start.jpg"
    end_path = OUTPUT / "toapis-video-canary-end.jpg"
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        image.save(start_path, "JPEG", quality=95, optimize=True, exif=b"")
        end = image.copy()
        draw = ImageDraw.Draw(end)
        width, height = end.size
        # Small deterministic visual motion cue near the robot, without text or canvas changes.
        x, y = int(width * 0.57), int(height * 0.42)
        radius = max(6, int(min(width, height) * 0.006))
        draw.ellipse((x - radius, y - radius * 2, x + radius, y), fill=(205, 55, 48))
        end.save(end_path, "JPEG", quality=95, optimize=True, exif=b"")
    for path in (start_path, end_path):
        with Image.open(path) as check:
            check.load()
            if check.mode != "RGB" or check.size != (2848, 1600) or check.getexif() or path.stat().st_size >= 10 * 1024 * 1024:
                raise RuntimeError("VIDEO_CANARY_FRAME_VALIDATION_FAILED")
        print(f"{path.name}:size=2848x1600 mime=image/jpeg sha256={digest(path)} bytes={path.stat().st_size}")
    if digest(start_path) == digest(end_path):
        raise RuntimeError("VIDEO_CANARY_FRAMES_MUST_DIFFER")
    return 0


if __name__ == "__main__":
    sys.exit(main())
