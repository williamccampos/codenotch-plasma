#!/usr/bin/env python3
"""Render hicolor PNG icons from the master SVG."""

import io
import shutil
import sys
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "icons" / "codenotch-plasma.svg"
ASSET_PNG = ROOT / "src" / "codenotch_plasma" / "assets" / "codenotch-plasma.png"
ASSET_SVG = ROOT / "src" / "codenotch_plasma" / "assets" / "codenotch-plasma.svg"


MENU_FILL = "#000000"


def svg_to_png(size: int) -> bytes:
    svg_text = SVG.read_text(encoding="utf-8").replace(
        'fill="#FFFFFF"',
        f'fill="{MENU_FILL}"',
    )
    return cairosvg.svg2png(
        bytestring=svg_text.encode("utf-8"),
        output_width=size,
        output_height=size,
        background_color="transparent",
    )


def main():
    if not SVG.is_file():
        print(f"missing {SVG}", file=sys.stderr)
        return 1

    sizes = (16, 22, 24, 32, 48, 64, 128, 256)
    for size in sizes:
        out_dir = ROOT / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "codenotch-plasma.png"
        target.write_bytes(svg_to_png(size))
        print(f"wrote {target}")

    scalable = ROOT / "icons" / "hicolor" / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SVG, scalable / "codenotch-plasma.svg")
    print(f"wrote {scalable / 'codenotch-plasma.svg'}")

    ASSET_SVG.write_text(SVG.read_text(encoding="utf-8"), encoding="utf-8")
    ASSET_PNG.write_bytes(svg_to_png(64))
    print(f"wrote {ASSET_SVG}")
    print(f"wrote {ASSET_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
