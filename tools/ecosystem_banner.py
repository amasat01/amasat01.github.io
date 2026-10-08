# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Generate the RAPTOR family banner: one picture of the whole ecosystem.

This file is the ONLY source of the four one-line package descriptions shown
in the banner. It writes ten self-contained SVGs -- focus in {family, aether,
hawk, eagle, raptor} x {light, dark} -- into this site's
``_static/ecosystem/``, and copies each package's light/dark pair into the
sibling repository next to this one (``<repo>/docs/_static/ecosystem/``),
where both that repo's README and its docs index page reference it.

The glyph artwork is the site's own ``_static/brand/glyph_*.svg`` (and
``family_raptor.svg``): its traced outlines are flattened, simplified and
rounded here so that each banner stays small (< 30 KB) while carrying all
four glyphs.

Usage::

    python tools/ecosystem_banner.py            # (re)write every copy
    python tools/ecosystem_banner.py --check    # exit 1 if any copy differs

``--check`` compares against the landing copies always, and against a
sibling repository's copies only when that repository is present.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

SITE = Path(__file__).resolve().parent.parent
BRAND = SITE / "_static" / "brand"
OUT_DIR = SITE / "_static" / "ecosystem"
REPO_SUBDIR = Path("docs") / "_static" / "ecosystem"

PACKAGES = ("hawk", "eagle", "aether", "raptor")
FOCI = ("family",) + PACKAGES
MODES = ("light", "dark")

# The single source of the wording. (lead, rest): the lead is drawn bold.
DESCRIPTIONS = {
    "hawk": ("Write it:", "one Python function per sample, compiled for GPU or CPU, with derivatives."),
    "eagle": ("Run it:", "millions of samples to completion; it picks the launch strategy."),
    "aether": ("Underneath:", "header-only C++/CUDA arrays and math, one source for GPU and CPU."),
    "raptor": ("The contract:", "one manifest and protocol every package speaks; zero dependencies."),
}
TITLE = "The RAPTOR family"
ROW_LABELS = ("YOUR PATH", "THE FOUNDATION")
ARROW_LABEL = "kernel"
YOU_ARE_HERE = "you are here"

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# Site tokens (_static/custom.css) for ink; brand glyph colours for artwork.
PALETTE = {
    "light": {
        "bg": "#fcfcfb", "card": "#ffffff", "border": "#e1e0d9", "ink": "#0b0b0b",
        "ink2": "#52514e", "muted": "#c3c2b7", "on_accent": "#ffffff",
        "accent": {"hawk": "#9a6a00", "eagle": "#c13360", "aether": "#0679b6", "raptor": "#7245ce"},
        "glyph": {"hawk": "#c18711", "eagle": "#cf416b", "aether": "#0398e3", "raptor": "#7d53dc"},
        "tint": 0.07,
    },
    "dark": {
        "bg": "#1a1a19", "card": "#242422", "border": "#3a3a37", "ink": "#ffffff",
        "ink2": "#c3c2b7", "muted": "#5d5c58", "on_accent": "#1a1a19",
        "accent": {"hawk": "#edb94a", "eagle": "#ef7fa0", "aether": "#8fd3f7", "raptor": "#a88bf0"},
        "glyph": {"hawk": "#edb94a", "eagle": "#ef7fa0", "aether": "#5fb6e4", "raptor": "#a88bf0"},
        "tint": 0.12,
    },
}

# ---------------------------------------------------------------- geometry
W, H = 960, 404
PAD = 24
CARD_W, CARD_H = 428, 124
COL_X = (PAD, W - PAD - CARD_W)                 # left / right column
ROW_Y = (94, 258)                                # top / bottom row
LAYOUT = {"hawk": (0, 0), "eagle": (1, 0), "aether": (0, 1), "raptor": (1, 1)}
GLYPH_BOX = 64
TEXT_X = 96                                      # text start inside a card
DESC_SIZE, DESC_LH = 17, 22
WRAP_PX = CARD_W - TEXT_X - 18
CHAR_EM = 0.50                                   # mean sans-serif glyph width, in em

# Glyph artwork: the masked parts of one outline (hawk/eagle/aether) and
# the separate raptor mark. Masks are the brand files' own, in their units.
SCALE = 2.0                                      # brand units per output unit
SIMPLIFY = 1.5                                   # max deviation, brand units
VIEWBOX = {"aether": (220, 1388, 1607, 969), "eagle": (1703, 479, 1140, 1272),
           "hawk": (1034, 1408, 1084, 886), "raptor": (423, 292, 2312, 2312)}
MASKS = {
    "hawk": [("poly", "1755,1680 1920,1680 2190,1740 2190,3072 1680,3072 1680,2100 1800,1920", "white"),
             ("circle", (1383, 1764, 312), "white"),
             ("poly", "1290,1485 1776,1485 1824,1605 1878,1680 1935,1860 1620,1860", "white"),
             ("poly", "1812,1476 1890,1200 2280,420 3072,0 3072,1500 1935,1515", "black")],
    "eagle": [("poly", "1776,1644 1794,1410 1890,1200 2280,420 3072,0 3072,1620 1920,1680", "white"),
              ("circle", (1383, 1764, 336), "black")],
    "aether": [("rect", None, "white"),
               ("poly", "1776,1644 1794,1410 1890,1200 2280,420 3072,0 3072,1620 1920,1680", "black"),
               ("poly", "1755,1680 1920,1680 3072,1620 3072,3072 1680,3072 1680,2100 1800,1920", "black"),
               ("poly", "1740,-500 3572,-500 3572,3572 1740,3572", "black")],
}


def _path_data(svg_name: str) -> str:
    text = (BRAND / svg_name).read_text()
    return re.search(r' d="([^"]*)"', text).group(1)


def _subpaths(d: str):
    toks = re.findall(r"[MCLZ]|-?\d*\.?\d+", d)
    subs, cur, cmd, i = [], None, None, 0
    while i < len(toks):
        if toks[i] in ("M", "C", "L", "Z"):
            cmd = toks[i]
            i += 1
            if cmd == "Z":
                subs.append(cur)
                cur = None
                continue
        n = 6 if cmd == "C" else 2
        v = [float(x) for x in toks[i:i + n]]
        i += n
        if cmd == "M":
            cur, cmd = [("M", v)], "L"
        else:
            cur.append((cmd, v))
    if cur:
        subs.append(cur)
    return subs


def _flatten(sub, steps=8):
    pts, p = [], None
    for c, v in sub:
        if c in ("M", "L"):
            p = (v[0], v[1])
            pts.append(p)
            continue
        (x0, y0), (x1, y1, x2, y2, x3, y3) = p, v
        for k in range(1, steps + 1):
            t = k / steps
            u = 1 - t
            pts.append((u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
                        u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3))
        p = (x3, y3)
    return pts


def _rdp(pts, eps):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-9
        best, bi = -1.0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            dist = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if dist > best:
                best, bi = dist, i
        if bi is not None and best > eps:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def _compact_path(svg_name: str) -> str:
    """Flatten, simplify and round a brand outline to a short relative path."""
    out = []
    for sub in _subpaths(_path_data(svg_name)):
        flat = _flatten(sub)
        mid = len(flat) // 2                      # closed loop: simplify two halves
        pts = _rdp(flat[:mid + 1], SIMPLIFY)[:-1] + _rdp(flat[mid:], SIMPLIFY)
        q = []
        for x, y in pts:
            r = (round(x / SCALE), round(y / SCALE))
            if not q or r != q[-1]:
                q.append(r)
        if len(q) < 3:
            continue
        rel, (px, py) = [], q[0]
        for x, y in q[1:]:
            rel.append(f"{x - px} {y - py}")
            px, py = x, y
        out.append(f"M{q[0][0]} {q[0][1]}l" + " ".join(rel).replace(" -", "-") + "z")
    return "".join(out)


def _s(v: float) -> str:
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _mask_defs() -> str:
    parts = [f'<filter id="soft" filterUnits="userSpaceOnUse" x="-250" y="-250" width="2036" height="2036">'
             f'<feGaussianBlur stdDeviation="{_s(16 / SCALE)}"/></filter>']
    for name, shapes in MASKS.items():
        inner = []
        for kind, geom, fill in shapes:
            if kind == "rect":
                inner.append(f'<rect x="-250" y="-250" width="2036" height="2036" fill="{fill}"/>')
            elif kind == "circle":
                cx, cy, r = (v / SCALE for v in geom)
                inner.append(f'<circle cx="{_s(cx)}" cy="{_s(cy)}" r="{_s(r)}" fill="{fill}"/>')
            else:
                pts = " ".join(",".join(_s(float(c) / SCALE) for c in p.split(","))
                               for p in geom.split())
                inner.append(f'<polygon points="{pts}" fill="{fill}"/>')
        parts.append(f'<mask id="m-{name}" maskUnits="userSpaceOnUse" x="-250" y="-250" width="2036" '
                     f'height="2036"><g filter="url(#soft)">{"".join(inner)}</g></mask>')
    return "".join(parts)


# ---------------------------------------------------------------- text
def _greedy(words, limit):
    lines, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > limit:
            lines.append(cur)
            cur = []
        cur.append(w)
    lines.append(cur)
    return lines


def _wrap(lead: str, rest: str):
    """Word-wrap 'lead rest' into the fewest lines that fit WRAP_PX, then
    balance them (no one-word last line); returns a list of word lists."""
    words = (lead + " " + rest).split()
    limit = int(WRAP_PX / (DESC_SIZE * CHAR_EM))
    n = len(_greedy(words, limit))
    while limit > 1 and len(_greedy(words, limit - 1)) == n:
        limit -= 1
    return _greedy(words, limit)


def alt_text(focus: str) -> str:
    """The alt text every page uses for this banner."""
    base = ("The RAPTOR family: hawk (write it), eagle (run it), aether (the C++/CUDA "
            "numerics underneath) and raptor (the shared contract)")
    return base + ("." if focus == "family" else f"; you are looking at {focus}.")


# ---------------------------------------------------------------- render
def _glyph(pkg: str, x: float, y: float, color: str) -> str:
    vx, vy, vw, vh = VIEWBOX[pkg]
    k = GLYPH_BOX / max(vw, vh)
    tx = x + (GLYPH_BOX - vw * k) / 2 - vx * k
    ty = y + (GLYPH_BOX - vh * k) / 2 - vy * k
    tf = f'translate({tx:.2f} {ty:.2f}) scale({k * SCALE:.5f})'
    if pkg == "raptor":
        return (f'<use xlink:href="#mark" transform="{tf}" fill="{color}" stroke="{color}" '
                f'stroke-width="{_s(34 / SCALE)}" stroke-linejoin="round"/>')
    return (f'<g transform="{tf}"><use xlink:href="#bird" mask="url(#m-{pkg})" '
            f'fill="{color}" fill-rule="evenodd"/></g>')


def _card(pkg: str, focus: str, mode: str) -> str:
    pal = PALETTE[mode]
    col, row = LAYOUT[pkg]
    x, y = COL_X[col], ROW_Y[row]
    lit = focus in ("family", pkg)
    here = focus == pkg
    accent = pal["accent"][pkg]
    out = []
    if here:
        out.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="{pal["card"]}"/>'
                   f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="{accent}" '
                   f'fill-opacity="{pal["tint"] * 2:.2f}" stroke="{accent}" stroke-width="3"/>')
    elif lit:
        out.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="{pal["card"]}"/>'
                   f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="{accent}" '
                   f'fill-opacity="{pal["tint"]:.2f}" stroke="{accent}" stroke-width="1.5"/>')
    else:
        out.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="{pal["card"]}" '
                   f'stroke="{pal["border"]}" stroke-width="1"/>')
    gy = y + (CARD_H - GLYPH_BOX) / 2
    out.append(_glyph(pkg, x + 18, gy, pal["glyph"][pkg] if lit else pal["muted"]))
    name_fill = accent if lit else pal["ink2"]
    out.append(f'<text x="{x + TEXT_X}" y="{y + 36}" font-size="22" font-weight="700" '
               f'fill="{name_fill}">{pkg}</text>')
    lead, rest = DESCRIPTIONS[pkg]
    lead_words = len(lead.split())
    body_fill = pal["ink"] if lit else pal["ink2"]
    for i, words in enumerate(_wrap(lead, rest)):
        ly = y + 62 + i * DESC_LH
        if i == 0:
            head, tail = " ".join(words[:lead_words]), " ".join(words[lead_words:])
            line = (f'<tspan font-weight="700" fill="{name_fill}">{escape(head)}</tspan>'
                    f' {escape(tail)}')
        else:
            line = escape(" ".join(words))
        out.append(f'<text x="{x + TEXT_X}" y="{ly}" font-size="{DESC_SIZE}" fill="{body_fill}">{line}</text>')
    if here:
        pw, ph = 104, 24
        px, py = x + CARD_W - pw - 14, y + 14
        out.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="12" fill="{accent}"/>'
                   f'<text x="{px + pw / 2:g}" y="{py + 16.5:g}" font-size="13" font-weight="700" '
                   f'text-anchor="middle" fill="{pal["on_accent"]}">{YOU_ARE_HERE}</text>')
    return "".join(out)


def render(focus: str, mode: str, bird: str, mark: str) -> str:
    pal = PALETTE[mode]
    desc = " ".join(f"{p}: {DESCRIPTIONS[p][0]} {DESCRIPTIONS[p][1]}" for p in PACKAGES)
    body = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="eco-t eco-d" '
        f'font-family="{FONT}">',
        f'<title id="eco-t">{escape(alt_text(focus))}</title>',
        f'<desc id="eco-d">{escape(desc)}</desc>',
        f'<defs>{_mask_defs()}<path id="bird" d="{bird}"/><path id="mark" d="{mark}"/></defs>',
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="18" fill="{pal["bg"]}" '
        f'stroke="{pal["border"]}"/>',
        f'<text x="{PAD}" y="50" font-size="26" font-weight="700" fill="{pal["ink"]}">{TITLE}</text>',
    ]
    for label, ry in zip(ROW_LABELS, ROW_Y):
        body.append(f'<text x="{PAD + 2}" y="{ry - 10}" font-size="12" font-weight="700" '
                    f'letter-spacing="1.2" fill="{pal["ink2"]}">{label}</text>')
    # arrow hawk -> eagle, through the gap between the top cards
    ax0, ax1 = COL_X[0] + CARD_W + 8, COL_X[1] - 8
    ay = ROW_Y[0] + CARD_H / 2
    arrow_lit = focus in ("family", "hawk", "eagle")
    acol = pal["ink"] if arrow_lit else pal["ink2"]
    body.append(f'<line x1="{ax0}" y1="{ay:g}" x2="{ax1 - 9}" y2="{ay:g}" stroke="{acol}" stroke-width="2.5"/>'
                f'<path d="M{ax1} {ay:g}l-12-7v14z" fill="{acol}"/>')
    body.append(f'<text x="{(ax0 + ax1) / 2:g}" y="{ay - 10:g}" font-size="12" text-anchor="middle" '
                f'fill="{pal["ink2"]}">{ARROW_LABEL}</text>')
    for pkg in PACKAGES:
        body.append(_card(pkg, focus, mode))
    body.append("</svg>\n")
    return "\n".join(body)


def filename(focus: str, mode: str) -> str:
    return f"ecosystem_{focus}_{mode}.svg"


def targets(siblings_root: Path):
    """(path, focus, mode) for every copy; sibling repos only when present."""
    out = [(OUT_DIR / filename(f, m), f, m) for f in FOCI for m in MODES]
    for pkg in PACKAGES:
        repo = siblings_root / pkg
        if repo.is_dir():
            out += [(repo / REPO_SUBDIR / filename(pkg, m), pkg, m) for m in MODES]
    return out


def build_all():
    bird, mark = _compact_path("family_raptor.svg"), _compact_path("glyph_raptor.svg")
    return {(f, m): render(f, m, bird, mark) for f in FOCI for m in MODES}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any copy differs; write nothing")
    ap.add_argument("--siblings", type=Path, default=SITE.parent,
                    help="directory holding the aether/hawk/eagle/raptor checkouts (default: next to this repo)")
    args = ap.parse_args(argv)
    svgs = build_all()
    bad = []
    for path, focus, mode in targets(args.siblings):
        want = svgs[(focus, mode)]
        if args.check:
            if not path.is_file() or path.read_text() != want:
                bad.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file() or path.read_text() != want:
                path.write_text(want)
                print(f"wrote {path}")
    if bad:
        for p in bad:
            print(f"stale or missing: {p}", file=sys.stderr)
        print("run: python tools/ecosystem_banner.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
