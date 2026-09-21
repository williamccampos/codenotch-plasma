#!/usr/bin/env python3
"""Render icon design candidates for review (not shipped in the package)."""

import io
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "icons" / "preview"
BG = "#2F4F5F"
SIZES = (16, 22, 48, 128)

DESIGNS = (
    ("Atual (v0.1.2)", ROOT / "icons" / "codenotch-plasma.svg"),
    ("A · Notch", PREVIEW / "a-notch.svg"),
    ("B · Hub", PREVIEW / "b-hub.svg"),
    ("C · Gota", PREVIEW / "c-drop.svg"),
    ("D · Notch limpo", PREVIEW / "d-notch-clean.svg"),
)


def svg_to_png(svg_path: Path, size: int) -> Image.Image:
    data = cairosvg.svg2png(
        url=str(svg_path),
        output_width=size,
        output_height=size,
        background_color="transparent",
    )
    return Image.open(io.BytesIO(data)).convert("RGBA")


def main():
    cell = 150
    header_h = 36
    pad = 24
    cols = len(SIZES) + 1
    rows = len(DESIGNS)
    width = pad * 2 + cols * cell
    height = pad * 2 + header_h + rows * cell
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for col, size in enumerate(SIZES, start=1):
        draw.text((pad + col * cell + 8, pad), f"{size}px", fill="#B8D4E3", font=font)
    draw.text((pad + 8, pad), "Design", fill="#B8D4E3", font=font)

    for row, (title, svg_path) in enumerate(DESIGNS):
        y = pad + header_h + row * cell
        draw.text((pad + 8, y + cell // 2 - 8), title, fill="#FFFFFF", font=font)
        for col, size in enumerate(SIZES, start=1):
            icon = svg_to_png(svg_path, size)
            x = pad + col * cell + (cell - size) // 2
            iy = y + (cell - size) // 2
            sheet.paste(icon, (x, iy), icon)

    out = PREVIEW / "preview-sheet.png"
    sheet.save(out)
    print(f"Preview: {out}")
    for size in (22, 128):
        for _title, svg_path in DESIGNS:
            target = PREVIEW / f"{svg_path.stem}-{size}.png"
            svg_to_png(svg_path, size).save(target)


if __name__ == "__main__":
    main()
