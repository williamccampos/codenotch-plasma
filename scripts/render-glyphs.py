#!/usr/bin/env python3
"""Build theme-aware provider glyphs with transparent backgrounds."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "codenotch_plasma" / "assets"
SIZE = 128
BG_TOLERANCE = 42


def _svg_bytes(svg_path: Path, fill: str) -> bytes:
    text = svg_path.read_text(encoding="utf-8")
    text = re.sub(r'fill="[^"]*"', f'fill="{fill}"', text, count=1)
    text = text.replace('fill="currentColor"', f'fill="{fill}"')
    if 'fill=' not in text.split(">", 1)[0]:
        text = text.replace("<svg ", f'<svg fill="{fill}" ', 1)
    return cairosvg.svg2png(bytestring=text.encode("utf-8"), output_width=SIZE, output_height=SIZE)


def _save_variant(svg_path: Path, name: str) -> None:
    for variant, fill in (("dark", "#FFFFFF"), ("light", "#000000")):
        png = _svg_bytes(svg_path, fill)
        out = ASSETS / f"{name}-{variant}.png"
        out.write_bytes(png)
        print(f"wrote {out.name}")


def _background_color(img: Image.Image) -> tuple[int, int, int]:
    w, h = img.size
    samples = [
        img.getpixel((0, 0)),
        img.getpixel((w - 1, 0)),
        img.getpixel((0, h - 1)),
        img.getpixel((w - 1, h - 1)),
    ]
    rs = sorted(p[0] for p in samples)
    gs = sorted(p[1] for p in samples)
    bs = sorted(p[2] for p in samples)
    return rs[len(rs) // 2], gs[len(gs) // 2], bs[len(bs) // 2]


def _distance(rgb: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    return sum((a - b) ** 2 for a, b in zip(rgb, bg)) ** 0.5


def _mask_from_png(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    bg = _background_color(img)
    mask = Image.new("L", img.size, 0)
    px = img.load()
    mpx = mask.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a < 16:
                continue
            if _distance((r, g, b), bg) <= BG_TOLERANCE:
                continue
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum > 20:
                mpx[x, y] = min(255, int(a * (lum / 255.0)))
    return mask


def _save_masked_variants(path: Path, name: str) -> None:
    mask = _mask_from_png(path)
    for variant, color in (("dark", (255, 255, 255, 255)), ("light", (0, 0, 0, 255))):
        out_img = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        glyph = Image.new("RGBA", mask.size, color)
        out_img = Image.composite(glyph, out_img, mask)
        out_path = ASSETS / f"{name}-{variant}.png"
        out_img.save(out_path, "PNG")
        print(f"wrote {out_path.name}")


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)

    for name in ("claude", "grok", "antigravity", "openai"):
        svg = ASSETS / f"{name}.svg"
        if not svg.exists() and name == "openai":
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffffff" fill-rule="evenodd">'
                '<path d="M21.55 10.004a5.416 5.416 0 00-.478-4.501c-1.217-2.09-3.662-3.166-6.05-2.66A5.59 5.59 0 0010.831 1C8.39.995 6.224 2.546 5.473 4.838A5.553 5.553 0 001.76 7.496a5.487 5.487 0 00.691 6.5 5.416 5.416 0 00.477 4.502c1.217 2.09 3.662 3.165 6.05 2.66A5.586 5.586 0 0013.168 23c2.443.006 4.61-1.546 5.361-3.84a5.553 5.553 0 003.715-2.66 5.488 5.488 0 00-.693-6.497v.001zm-8.381 11.558a4.199 4.199 0 01-2.675-.954c.034-.018.093-.05.132-.074l4.44-2.53a.71.71 0 00.364-.623v-6.176l1.877 1.069c.02.01.033.029.036.05v5.115c-.003 2.274-1.87 4.118-4.174 4.123zM4.192 17.78a4.059 4.059 0 01-.498-2.763c.032.02.09.055.131.078l4.44 2.53c.225.13.504.13.73 0l5.42-3.088v2.138a.068.068 0 01-.027.057L9.9 19.288c-1.999 1.136-4.552.46-5.707-1.51h-.001zM3.023 8.216A4.15 4.15 0 015.198 6.41l-.002.151v5.06a.711.711 0 00.364.624l5.42 3.087-1.876 1.07a.067.067 0 01-.063.005l-4.489-2.559c-1.995-1.14-2.679-3.658-1.53-5.63h.001zm15.417 3.54l-5.42-3.088L14.896 7.6a.067.067 0 01.063-.006l4.489 2.557c1.998 1.14 2.683 3.662 1.529 5.633a4.163 4.163 0 01-2.174 1.807V12.38a.71.71 0 00-.363-.623zm1.867-2.773a6.04 6.04 0 00-.132-.078l-4.44-2.53a.731.731 0 00-.729 0l-5.42 3.088V7.325a.068.068 0 01.027-.057L14.1 4.713c2-1.137 4.555-.46 5.707 1.513.487.833.664 1.809.499 2.757h.001zm-11.741 3.81l-1.877-1.068a.065.065 0 01-.036-.051V6.559c.001-2.277 1.873-4.122 4.181-4.12.976 0 1.92.338 2.671.954-.034.018-.092.05-.131.073l-4.44 2.53a.71.71 0 00-.365.623l-.003 6.173v.002zm1.02-2.168L12 9.25l2.414 1.375v2.75L12 14.75l-2.415-1.375v-2.75z"/>'
                "</svg>\n",
                encoding="utf-8",
            )
            print(f"wrote {svg.name}")
        if svg.exists():
            _save_variant(svg, name)

    for name in ("cursor", "kiro"):
        src = ASSETS / f"{name}.png"
        if src.exists():
            _save_masked_variants(src, name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
