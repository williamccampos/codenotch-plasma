#!/usr/bin/env python3
"""Render hicolor PNG icons from the vector renderer."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt5.QtWidgets import QApplication

from codenotch_plasma.icons import render_app_icon


def main():
    app = QApplication([])
    sizes = (16, 22, 24, 32, 48, 64, 128, 256)
    for size in sizes:
        out_dir = ROOT / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "codenotch-plasma.png"
        render_app_icon(size).save(str(target))
        print(f"wrote {target}")
    scalable = ROOT / "icons" / "hicolor" / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    source = ROOT / "icons" / "codenotch-plasma.svg"
    dest = scalable / "codenotch-plasma.svg"
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
