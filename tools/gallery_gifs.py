# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Build the gallery animations: ``_static/gallery/NAME_{light,dark}.gif``, never committed.

Each one is an animation a hawk or eagle docs notebook already writes (the paired checkouts hold them under
``docs/_static/anim``). The wide ones are copied; the small ones are scaled down to their gallery size. Needs Pillow
and no GPU.

    python tools/gallery_gifs.py [HAWK_CHECKOUT [EAGLE_CHECKOUT]]      # default: ./hawk and ./eagle
"""
import pathlib
import shutil
import sys

from PIL import Image

SITE = pathlib.Path(__file__).resolve().parent.parent
# gallery name: (repo, animation stem in that repo's docs/_static/anim, width to scale to or None to copy)
GIFS = {
    "heat": ("hawk", "heat_diffusion", 208),
    "fluids": ("hawk", "shallow_water", 208),
    "monte_carlo": ("eagle", "monte_carlo_early_termination", 384),
    "combustion": ("hawk", "ignition_delay", None),
    "nuclear": ("hawk", "neutron_histories", None),
    "biochemistry": ("hawk", "enzyme_fits", None),
    "control": ("hawk", "gain_tuning", None),
    "signal": ("hawk", "tone_detection", None),
}


def scaled(src: pathlib.Path, dst: pathlib.Path, width: int) -> None:
    im = Image.open(src)
    height = round(im.height * width / im.width)
    frames, durations = [], []
    for i in range(im.n_frames):
        im.seek(i)
        durations.append(im.info.get("duration", 70))
        frame = im.convert("RGB").resize((width, height), Image.LANCZOS)
        frames.append(frame.quantize(colors=48, method=Image.Quantize.MEDIANCUT))
    frames[0].save(dst, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


def main(argv) -> int:
    roots = {"hawk": pathlib.Path(argv[1] if len(argv) > 1 else SITE / "hawk"),
             "eagle": pathlib.Path(argv[2] if len(argv) > 2 else SITE / "eagle")}
    out = SITE / "_static" / "gallery"
    out.mkdir(parents=True, exist_ok=True)
    for name, (repo, stem, width) in GIFS.items():
        for theme in ("light", "dark"):
            src = roots[repo] / "docs" / "_static" / "anim" / f"{stem}_{theme}.gif"
            if not src.is_file():
                print(f"error: {src} not found: check out the {repo} repository next to this one", file=sys.stderr)
                return 1
            dst = out / f"{name}_{theme}.gif"
            if width:
                scaled(src, dst, width)
            else:
                shutil.copyfile(src, dst)
            print("wrote", dst.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
