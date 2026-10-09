# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Generate the RAPTOR family cards: four clickable cards, one per package.

This file is the ONLY source of the four one-line package descriptions. It
writes, for a focus in {family, aether, hawk, eagle, raptor} (the package a
page is about, or ``family`` for the landing page):

* ``ecosystem_card_<pkg>_<focus>_<light|dark>.svg`` -- one self-contained SVG
  per card (READMEs: GitHub and PyPI cannot run CSS), and
* ``ecosystem_cards_<focus>.html`` -- the live HTML cards with their CSS
  (docs sites; colours switch instantly, only the hover scale animates).

The landing copy goes into this site's ``_static/ecosystem/``; each package's
own focus is copied into the sibling repository next to this one
(``<repo>/docs/_static/ecosystem/``), where that repo's README and docs index
page reference it.

The glyph artwork is the site's own ``_static/brand/glyph_*.svg`` (and
``family_raptor.svg``): its traced outlines are flattened, simplified and
rounded here so that each banner stays small (< 30 KB) while carrying all
four glyphs.

Usage::

    python tools/ecosystem_banner.py            # (re)write every copy
    python tools/ecosystem_banner.py --check    # exit 1 if any copy differs

``--check`` covers every output. It compares against the landing copies always, and against a
sibling repository's copies only when that repository is present.
"""
from __future__ import annotations

import argparse
import html
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
SITE_URL = "https://amasat01.github.io"
RAW_URL = "https://raw.githubusercontent.com/amasat01"
# URL of each card's docs site (the family card row links the landing page separately).
PKG_URL = {p: f"{SITE_URL}/{p}/" for p in ("hawk", "eagle", "aether", "raptor")}

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
CARD_W, CARD_H = 428, 124
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
    """One card drawn with its top-left corner at the origin."""
    pal = PALETTE[mode]
    x, y = 0, 0
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




def card_alt(pkg: str) -> str:
    lead, rest = DESCRIPTIONS[pkg]
    return f"{pkg}: {lead} {rest}"


def render_card_svg(pkg: str, focus: str, mode: str, bird: str, mark: str) -> str:
    """A single self-contained card (README image); focus lights the 'here' card."""
    path = f'<path id="mark" d="{mark}"/>' if pkg == "raptor" else f'<path id="bird" d="{bird}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="-2 -2 {CARD_W + 4} {CARD_H + 4}" width="{CARD_W + 4}" height="{CARD_H + 4}" '
            f'role="img" aria-label="{html.escape(card_alt(pkg))}" font-family="{FONT}">'
            f'<defs>{_mask_defs()}{path}</defs>{_card(pkg, focus, mode)}</svg>\n')


def _css_vars(mode: str) -> str:
    P = PALETTE[mode]
    s = (f'--bg:{P["bg"]};--card:{P["card"]};--border:{P["border"]};--ink:{P["ink"]};--ink2:{P["ink2"]};'
         f'--muted:{P["muted"]};--on:{P["on_accent"]};--tint:{round(P["tint"] * 100)}%;')
    for k in PACKAGES:
        s += f'--a-{k}:{P["accent"][k]};--g-{k}:{P["glyph"][k]};'
    return s


def cards_css() -> str:
    """CSS of the live cards. Colours switch INSTANTLY (hover and theme change
    alike): only transform and box-shadow ever transition."""
    return f"""/* RAPTOR family cards (generated by tools/ecosystem_banner.py -- do not edit). */
.eco-wrap{{container-type:inline-size;margin:1.5em 0}}
.eco-wrap{{{_css_vars("light")}--font:{FONT};}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]) .eco-wrap{{{_css_vars("dark")}}}}}
[data-theme="dark"] .eco-wrap{{{_css_vars("dark")}}}
.eco{{box-sizing:border-box;width:960px;max-width:100%;margin:0 auto;padding:24px;background:var(--bg);border:1px solid var(--border);border-radius:18px;display:grid;grid-template-columns:minmax(0,428px) minmax(56px,1fr) minmax(0,428px);grid-template-rows:auto auto auto auto auto;font-family:var(--font);line-height:normal}}
.eco .eco-title{{grid-column:1/-1;margin:0 0 20px;font-size:26px;line-height:32px;font-weight:700;color:var(--ink)}}
.eco .eco-title a{{color:inherit;text-decoration:none}}
.eco .eco-title a:hover,.eco .eco-title a:focus-visible{{text-decoration:underline}}
.eco .eco-label{{grid-column:1/-1;font-size:12px;font-weight:700;letter-spacing:1.2px;color:var(--ink2);margin:0 0 -2px 2px;height:16px}}
.eco .eco-label.l1{{grid-row:2}}
.eco .eco-label.l2{{grid-row:4;margin-top:24px}}
.eco>a:nth-of-type(1){{grid-row:3;grid-column:1}}
.eco>.arrow{{grid-row:3;grid-column:2}}
.eco>a:nth-of-type(2){{grid-row:3;grid-column:3}}
.eco>a:nth-of-type(3){{grid-row:5;grid-column:1}}
.eco>a:nth-of-type(4){{grid-row:5;grid-column:3}}
.eco .arrow{{align-self:center;justify-self:center;width:40px;text-align:center;font-size:11px;white-space:nowrap;color:var(--ink2)}}
.eco .arrow svg{{width:40px;height:14px;display:block;stroke:var(--ink2);stroke-width:2.5;fill:var(--ink2);margin-top:4px}}
.eco a.eco-card{{--accent:var(--ink2);--g:var(--muted);position:relative;box-sizing:border-box;display:flex;align-items:center;gap:14px;width:100%;min-height:124px;padding:0 18px;border-radius:14px;border:1px solid var(--border);background:var(--card);color:var(--ink2);text-decoration:none;transition:transform .16s ease,box-shadow .16s ease;transform-origin:center}}
.eco a.eco-card[data-pkg=hawk]{{--accent:var(--a-hawk);--g:var(--g-hawk)}}
.eco a.eco-card[data-pkg=eagle]{{--accent:var(--a-eagle);--g:var(--g-eagle)}}
.eco a.eco-card[data-pkg=aether]{{--accent:var(--a-aether);--g:var(--g-aether)}}
.eco a.eco-card[data-pkg=raptor]{{--accent:var(--a-raptor);--g:var(--g-raptor)}}
.eco .glyph{{flex:none;width:64px;height:64px;color:var(--muted)}}
.eco .txt{{display:block;min-width:0}}
.eco .name{{display:block;font-size:22px;line-height:28px;font-weight:700;color:var(--ink2);margin-bottom:6px}}
.eco .desc{{display:block;font-size:17px;line-height:22px;font-weight:400;color:var(--ink2)}}
.eco .desc b{{font-weight:700;color:var(--ink2)}}
.eco .pill{{position:absolute;top:13px;right:13px;height:24px;line-height:24px;padding:0 12px;border-radius:12px;font-size:13px;font-weight:700;background:var(--accent);color:var(--on)}}
.eco a.eco-card.lit,.eco a.eco-card.here,.eco a.eco-card:hover,.eco a.eco-card:focus-visible,.eco a.eco-card.is-hover{{border-color:var(--accent);background:color-mix(in srgb,var(--accent) var(--tint),var(--card))}}
.eco a.eco-card.lit{{border-width:1.5px;padding:0 17.5px}}
.eco a.eco-card.here{{border-width:3px;padding:0 16px;background:color-mix(in srgb,var(--accent) calc(var(--tint)*2),var(--card))}}
.eco a.eco-card.lit .glyph,.eco a.eco-card.here .glyph,.eco a.eco-card:hover .glyph,.eco a.eco-card:focus-visible .glyph,.eco a.eco-card.is-hover .glyph{{color:var(--g)}}
.eco a.eco-card.lit .name,.eco a.eco-card.here .name,.eco a.eco-card:hover .name,.eco a.eco-card:focus-visible .name,.eco a.eco-card.is-hover .name,.eco a.eco-card.lit .desc b,.eco a.eco-card.here .desc b,.eco a.eco-card:hover .desc b,.eco a.eco-card:focus-visible .desc b,.eco a.eco-card.is-hover .desc b{{color:var(--accent)}}
.eco a.eco-card.lit .desc,.eco a.eco-card.here .desc,.eco a.eco-card:hover .desc,.eco a.eco-card:focus-visible .desc,.eco a.eco-card.is-hover .desc{{color:var(--ink)}}
.eco a.eco-card:hover,.eco a.eco-card:focus-visible,.eco a.eco-card.is-hover{{transform:scale(1.04);z-index:1;box-shadow:0 6px 18px color-mix(in srgb,var(--accent) 22%,transparent);border-width:2px;padding:0 17px}}
.eco a.eco-card:hover .desc,.eco a.eco-card:focus-visible .desc,.eco a.eco-card.is-hover .desc{{font-weight:500}}
.eco a.eco-card:hover .desc b,.eco a.eco-card:focus-visible .desc b,.eco a.eco-card.is-hover .desc b,.eco a.eco-card:hover .name,.eco a.eco-card:focus-visible .name,.eco a.eco-card.is-hover .name{{font-weight:800}}
.eco a.eco-card:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}
@media (prefers-reduced-motion:reduce){{.eco a.eco-card{{transition:none}}.eco a.eco-card:hover,.eco a.eco-card:focus-visible,.eco a.eco-card.is-hover{{transform:none}}}}
@container (max-width:900px){{.eco{{display:flex;flex-direction:column;gap:14px}}.eco .arrow,.eco .eco-label,.eco>span{{display:none}}.eco .eco-title{{margin:0}}}}
"""


def render_cards_html(focus: str, bird: str, mark: str) -> str:
    """Fragment for a docs page: <style>, shared glyph defs and the four cards."""
    defs = (f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{_mask_defs()}'
            f'<path id="bird" d="{bird}"/><path id="mark" d="{mark}"/></defs></svg>')

    def card(p):
        lead, rest = DESCRIPTIONS[p]
        g = _glyph(p, 0, 0, "currentColor").replace("xlink:href", "href")
        cls = "eco-card here" if p == focus else ("eco-card lit" if focus == "family" else "eco-card")
        cur = ' aria-current="page"' if p == focus else ""
        pill = f'<span class="pill">{YOU_ARE_HERE}</span>' if p == focus else ""
        return (f'<a href="{PKG_URL[p]}" data-pkg="{p}" class="{cls}"{cur}>'
                f'<svg class="glyph" viewBox="0 0 64 64" aria-hidden="true">{g}</svg>'
                f'<span class="txt"><span class="name">{p}</span>'
                f'<span class="desc"><b>{html.escape(lead)}</b> {html.escape(rest)}</span></span>{pill}</a>')

    c = {p: card(p) for p in PACKAGES}
    title = TITLE if focus == "family" else f'<a href="{SITE_URL}/">{TITLE}</a>'
    arrow = (f'<div class="arrow" aria-hidden="true"><span>{ARROW_LABEL}</span><svg viewBox="0 0 40 14">'
             f'<line x1="0" y1="7" x2="30" y2="7"/><path d="M40 7l-12-7v14z"/></svg></div>')
    return (f'<div class="eco-wrap">\n<style>\n{cards_css()}</style>\n{defs}\n'
            f'<nav class="eco" aria-label="{TITLE}">\n<div class="eco-title">{title}</div>\n'
            f'<div class="eco-label l1">{ROW_LABELS[0]}</div><div class="eco-label l2">{ROW_LABELS[1]}</div>\n'
            f'{c["hawk"]}{arrow}{c["eagle"]}\n{c["aether"]}<span></span>{c["raptor"]}\n</nav>\n</div>\n')


def card_filename(pkg: str, focus: str, mode: str) -> str:
    return f"ecosystem_card_{pkg}_{focus}_{mode}.svg"


def html_filename(focus: str) -> str:
    return f"ecosystem_cards_{focus}.html"


def outputs(siblings_root: Path) -> dict:
    """{path: text} for every output. The landing site carries the family
    focus; a sibling repository carries its own focus, when it is present."""
    bird, mark = _compact_path("family_raptor.svg"), _compact_path("glyph_raptor.svg")

    def bundle(directory: Path, focus: str) -> dict:
        out = {directory / html_filename(focus): render_cards_html(focus, bird, mark)}
        for pkg in PACKAGES:
            for mode in MODES:
                out[directory / card_filename(pkg, focus, mode)] = render_card_svg(pkg, focus, mode, bird, mark)
        return out

    out = bundle(OUT_DIR, "family")
    for pkg in PACKAGES:
        repo = siblings_root / pkg
        if repo.is_dir():
            out.update(bundle(repo / REPO_SUBDIR, pkg))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any copy differs; write nothing")
    ap.add_argument("--siblings", type=Path, default=SITE.parent,
                    help="directory holding the aether/hawk/eagle/raptor checkouts (default: next to this repo)")
    args = ap.parse_args(argv)
    bad = []
    for path, want in outputs(args.siblings).items():
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
