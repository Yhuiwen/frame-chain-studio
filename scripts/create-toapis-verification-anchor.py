from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw


WIDTH = 1280
HEIGHT = 720
MAX_BYTES = 1024 * 1024


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = repo_root / ".run" / "toapis-verification-anchor.png"
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (WIDTH, HEIGHT), (229, 231, 233))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 565, WIDTH, HEIGHT), fill=(210, 212, 214))
    draw.ellipse((305, 535, 690, 625), fill=(188, 190, 192))
    draw.ellipse((820, 530, 1090, 610), fill=(188, 190, 192))

    # Simple red toy robot, centered left.
    draw.rounded_rectangle((385, 220, 610, 390), radius=28, fill=(201, 48, 48), outline=(92, 35, 35), width=7)
    draw.ellipse((430, 275, 458, 303), fill=(245, 245, 240))
    draw.ellipse((535, 275, 563, 303), fill=(245, 245, 240))
    draw.rectangle((478, 183, 516, 222), fill=(115, 118, 120))
    draw.ellipse((481, 164, 513, 195), fill=(201, 48, 48), outline=(92, 35, 35), width=5)
    draw.rounded_rectangle((405, 395, 590, 555), radius=22, fill=(211, 55, 55), outline=(92, 35, 35), width=7)
    draw.rounded_rectangle((335, 410, 405, 505), radius=18, fill=(201, 48, 48), outline=(92, 35, 35), width=6)
    draw.rounded_rectangle((590, 410, 660, 505), radius=18, fill=(201, 48, 48), outline=(92, 35, 35), width=6)
    draw.rounded_rectangle((430, 548, 480, 610), radius=12, fill=(115, 118, 120))
    draw.rounded_rectangle((520, 548, 570, 610), radius=12, fill=(115, 118, 120))

    # Blue cube on the right.
    draw.polygon([(860, 360), (1040, 330), (1090, 385), (910, 420)], fill=(70, 135, 210))
    draw.polygon([(860, 360), (910, 420), (910, 570), (860, 505)], fill=(48, 102, 171))
    draw.polygon([(910, 420), (1090, 385), (1090, 535), (910, 570)], fill=(55, 116, 196))

    image.save(output, format="PNG", optimize=True)
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.mode != "RGB" or decoded.size != (WIDTH, HEIGHT):
            raise RuntimeError("Generated anchor failed RGB/dimension validation.")
        if decoded.getexif():
            raise RuntimeError("Generated anchor unexpectedly contains EXIF metadata.")
    content = output.read_bytes()
    if len(content) >= MAX_BYTES:
        raise RuntimeError("Generated anchor must remain below 1 MB.")
    print("path=.run/toapis-verification-anchor.png")
    print(f"width={WIDTH}")
    print(f"height={HEIGHT}")
    print("mode=RGB")
    print("exif=false")
    print(f"bytes={len(content)}")
    print(f"sha256={hashlib.sha256(content).hexdigest()}")


if __name__ == "__main__":
    main()
