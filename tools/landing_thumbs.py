# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Still thumbnails of the five gallery pictures for the landing page: ``_static/figures/landing/NAME_{light,dark}.png``.

The gallery animations are GIFs (hundreds of kB each); the landing page shows their first frame instead, a square crop
of the same picture at 2x its display size, and links to the gallery for the real thing.

    python tools/landing_thumbs.py
"""
import pathlib

from PIL import Image

SITE = pathlib.Path(__file__).resolve().parent.parent
NAMES = {"fem": "png", "heat": "gif", "fluids": "gif", "monte_carlo": "gif", "binning": "png"}
SIDE = 200  # displayed at 100 px: 2x


def main() -> int:
    out = SITE / "_static" / "figures" / "landing"
    out.mkdir(parents=True, exist_ok=True)
    for name, ext in NAMES.items():
        for theme in ("light", "dark"):
            im = Image.open(SITE / "_static" / "gallery" / f"{name}_{theme}.{ext}")
            im.seek(0)
            im = im.convert("RGBA")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((SIDE, SIDE), Image.LANCZOS)
            im.save(out / f"{name}_{theme}.png", optimize=True)
            print("wrote", name, theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
