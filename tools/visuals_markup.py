# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Markup of the two coverage visuals (see visuals.py): the two-worlds chart and the rosette, as inline SVG plus the data
tables and the JSON the script reads. No dependency on the site; styled by the classes in custom.css and driven by
js/visuals.js."""
import html
import json
import math

import radar_icons
import visuals as V

ESC = html.escape


def sprite(ids, keys):
    """The hidden ``<symbol>`` sheet the chart's icons are drawn from (inline, no external files)."""
    syms = "".join(f'<symbol id="{ids}-{k}" viewBox="0 0 24 24">{radar_icons.ICONS[k]}</symbol>' for k in keys)
    return f'<svg class="vis-icons" width="0" height="0" aria-hidden="true" focusable="false"><defs>{syms}</defs></svg>'


def icon_g(ids, key, x, y, size, cls="ic", extra=""):
    return (f'<g class="{cls}" transform="translate({x - size / 2:.1f} {y - size / 2:.1f})"{extra}>'
            f'<use href="#{ids}-{key}" width="{size}" height="{size}"/></g>')


def _tspans(x, lines, lh, first_dy=0.0):
    return "".join(f'<tspan x="{x:.1f}" dy="{first_dy if j == 0 else lh}">{ESC(l)}</tspan>' for j, l in enumerate(lines))


def _arcs(x, y, r, tools_present, tools_all, vars_):
    """One short arc round a node per tool that covers it, in the tool's colour, spread evenly round the node."""
    out = []
    seg = 2 * math.pi / len(tools_all)
    for j, t in enumerate(tools_all):
        if t not in tools_present:
            continue
        a0, a1 = -math.pi / 2 + j * seg + 0.1, -math.pi / 2 + (j + 1) * seg - 0.1
        out.append(f'<path class="arc" data-tool="{ESC(t, quote=True)}" style="stroke:var({vars_[t]})" '
                   f'd="M{x + r * math.cos(a0):.1f} {y + r * math.sin(a0):.1f}A{r:.1f} {r:.1f} 0 0 1 '
                   f'{x + r * math.cos(a1):.1f} {y + r * math.sin(a1):.1f}"/>')
    return "".join(out)


_CACHE = {}


def _signature(table, tools):
    """What the geometry depends on: each feature's coverage by each tool, and whether the device has a reading for it."""
    return tuple((f, tuple(V.feature_covered(table, f, t) for t in tools), V.measured_anywhere(table, f)) for f, _l, _k in V.FEATURES)


def cached_worlds(table, tools, layout_key, layout):
    """`V.Worlds`, computed once per coverage pattern (several devices share one)."""
    key = ("w", layout_key, tuple(t[0] for t in tools), _signature(table, [t[0] for t in tools]))
    if key not in _CACHE:
        _CACHE[key] = V.Worlds(table, tools, layout)
    return _CACHE[key]


def cached_rosette(table, tools, mode, sector="ensemble"):
    key = ("r", mode, sector, tuple(t[0] for t in tools), _signature(table, [t[0] for t in tools]))
    if key not in _CACHE:
        _CACHE[key] = V.Rosette(table, tools, mode, sector)
    return _CACHE[key]


def block_aria(table, tools, key):
    who = [t for t in tools if V.block_covered(table, key, t)]
    return f"{V.BLOCK[key][1]}: " + (f"covered by {', '.join(who)}" if who else "covered by no tool on this device")


# --------------------------------------------------------------------------- the two worlds
def worlds_svg(W, ids, uid, aria):
    """The two-worlds chart of one `V.Worlds`: soft world regions, each tool's rounded convex hull(s), the blocks (a node
    with one arc per covering tool, its icon and, on the wide chart, its label)."""
    wide = bool(W.lay["fs"])
    w, h = W.lay["size"]
    node, isz = W.node, W.lay["icon"]
    sx, sy, sr = W.lay["sim"]
    ax, ay, ar = W.lay["ai"]
    out = [f'<svg class="worlds-svg {"worlds-svg-wide" if wide else "worlds-svg-narrow"}" viewBox="0 0 {w} {h}" role="group" aria-label="{ESC(aria, quote=True)}">']
    out.append(f'<defs><radialGradient id="gsim-{uid}"><stop offset="45%" stop-color="var(--world-sim)" stop-opacity=".55"/>'
               f'<stop offset="78%" stop-color="var(--world-sim)" stop-opacity=".22"/><stop offset="100%" stop-color="var(--world-sim)" stop-opacity="0"/></radialGradient>'
               f'<radialGradient id="gai-{uid}"><stop offset="40%" stop-color="var(--tool-pytorch)" stop-opacity=".22"/>'
               f'<stop offset="75%" stop-color="var(--tool-pytorch)" stop-opacity=".09"/><stop offset="100%" stop-color="var(--tool-pytorch)" stop-opacity="0"/></radialGradient></defs>')
    out.append(f'<circle class="world world-sim" cx="{sx:.0f}" cy="{sy:.0f}" r="{sr:.0f}" fill="url(#gsim-{uid})"/>'
               f'<circle class="world world-ai" cx="{ax:.0f}" cy="{ay:.0f}" r="{ar:.0f}" fill="url(#gai-{uid})"/>')
    for key, tt in W.titles().items():
        fs1, fs2 = tt["fs"]
        name = "Simulation" if key == "sim" else "AI"
        sub = tt["lines"][1:] if len(tt["lines"]) > 1 else ()
        out.append(f'<text class="world-title" data-world="{key}" text-anchor="{tt["anchor"]}" x="{tt["x"]:.1f}" y="{tt["y"]:.1f}" style="font-size:{fs1}px">{name}'
                   + "".join(f'<tspan class="world-sub" x="{tt["x"]:.1f}" dy="{tt["lh"]}" style="font-size:{fs2}px">{ESC(s_)}</tspan>' for s_ in sub) + "</text>")
    for t in W.tools:
        for i, (blob, members) in enumerate(W.pieces[t]):
            out.append(f'<path class="blob" data-tool="{ESC(t, quote=True)}" data-piece="{i}" data-blocks="{" ".join(members)}" '
                       f'style="--c:var({W.vars[t]})" d="{blob.path()}"/>')
    names = W.name_boxes() if wide else {}
    for t, nb in names.items():
        out.append(f'<text class="bname" data-tool="{ESC(t, quote=True)}" text-anchor="middle" x="{nb["x"]:.1f}" y="{nb["y"]:.1f}" style="fill:var({W.vars[t]})">{ESC(t)}</text>')
    for key in V.BLOCKS_KEYS:
        b = V.BLOCK[key]
        x, y = W.pos[key]
        who = [t for t in W.tools if V.block_covered(W.table, key, t)]
        feats = V.block_features(W.table, key)
        q = all(f not in V.MEASURED for f in b[5])
        out.append(f'<g class="wnode{" none" if not who else ""}" data-block="{key}" data-features="{" ".join(b[5])}" tabindex="0" role="button" '
                   f'aria-label="{ESC(block_aria(W.table, W.tools, key), quote=True)}">'
                   f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="{W.node + 6}"/>'
                   f'<circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="{W.node}"/>' + _arcs(x, y, W.node + 1.5, who, W.tools, W.vars)
                   + icon_g(ids, b[3], x, y, isz))
        if wide:
            lab = W.labels[key]
            if lab["disp"] > 30:        # a label moved well away from its node is tied to it by a thin leader
                l_, t_, r_, b_ = lab["box"][:4]
                px, py = min(max(x, l_), r_), min(max(y, t_), b_)
                d = math.hypot(px - x, py - y) or 1.0
                ux, uy = (px - x) / d, (py - y) / d
                out.append(f'<line class="leader" x1="{x + ux * (W.node + 4):.1f}" y1="{y + uy * (W.node + 4):.1f}" x2="{px - ux * 2:.1f}" y2="{py - uy * 2:.1f}"/>')
            out.append(f'<text class="nlabel{" q" if q else ""}" data-n="{key}" text-anchor="{lab["box"][4]}" x="{lab["box"][5]:.1f}" y="{lab["box"][6]:.1f}">'
                       + _tspans(lab["box"][5], lab["lines"], W.lay["fs"] + 1) + "</text>")
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def _fmt_pass(feature, entry):
    if entry is None:
        return "no reading"
    return entry.get("v", "")


def feature_rows(table, tools, features=None):
    """[(feature, label, measured, {tool: (value text, detail text, covers)})] for the feature table."""
    rows = []
    for f, label, kind in V.FEATURES:
        if features is not None and f not in features:
            continue
        cells = {}
        for t in tools:
            e = table.get(f, {}).get(t)
            cells[t] = (None, None, False) if e is None else (e.get("v", ""), e.get("r", ""), V.covers(f, e))
        rows.append((f, label, kind == "m", cells))
    return rows


def worlds_json(table, tools):
    """What the popover shows for each block and each feature, in the tables' own words."""
    blocks = {}
    for b in V.BLOCKS:
        k = b[0]
        blocks[k] = {"l": b[1], "f": [[f, V.LABEL[f]] for f in b[5]], "x": [f for f in b[5] if f not in V.block_features(table, k)],
                     "w": [t for t in tools if V.block_covered(table, k, t)]}
    vals = {}
    for f, _l, _m, cells in feature_rows(table, tools):
        measured = f in V.MEASURED
        vals[f] = {t: ([c[0], c[1] if measured else "", 1 if c[2] else 0] if c[0] is not None else None) for t, c in cells.items()}
    return {"blocks": blocks, "vals": vals}


def worlds_tables(table, tools):
    """The data behind the chart: block coverage, then every feature's reading per tool with whether it meets the rule."""
    th = "".join(f'<th scope="col">{ESC(t)}</th>' for t in tools)
    rows = []
    for b in V.BLOCKS:
        k = b[0]
        need = ", ".join(V.LABEL[f] for f in b[5])
        cells = "".join(f'<td>{"covered" if V.block_covered(table, k, t) else "–"}</td>' for t in tools)
        rows.append(f'<tr data-block="{k}"><th scope="row">{ESC(b[1])}</th><td class="needs">{ESC(need)}</td>{cells}</tr>')
    t1 = (f'<table class="worlds-table worlds-blocks"><caption>Blocks of work: a tool covers a block when it covers every feature the block needs</caption>'
          f'<thead><tr><th scope="col">Block</th><th scope="col">Needs</th>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>')
    rows = []
    for f, label, measured, cells in feature_rows(table, tools):
        tds = []
        for t in tools:
            v, r, ok = cells[t]
            if v is None:
                tds.append('<td class="miss">no reading</td>')
            else:
                text = f"{v} ({r})" if measured else f"{v}"
                why = "" if measured or not r else f'<br><small class="why">{ESC(r)}</small>'
                tds.append(f'<td class="{"ok" if ok else "no"}">{ESC(text)}{" ✓" if ok else ""}{why}</td>')
        qc = "" if measured else ' class="q"'
        rows.append(f'<tr data-feature="{f}"><th scope="row"{qc}>{ESC(label)}</th>{"".join(tds)}</tr>')
    t2 = (f'<table class="worlds-table worlds-features"><caption>Features: measured readings, and the rubric scores (judgement). A tick marks '
          f'a feature the tool covers: within {V.WITHIN:g}× of the best tool, or {V.RUBRIC_MIN} of 5</caption>'
          f'<thead><tr><th scope="col">Feature</th>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>')
    return t1 + t2


def key_list(W, ids):
    """The icon -> block list under the phone-width chart: every icon named once."""
    items = []
    for key in V.BLOCKS_KEYS:
        b = V.BLOCK[key]
        who = [V.MONO.get(t, t) for t in W.tools if V.block_covered(W.table, key, t)]
        items.append(f'<li data-block="{key}" data-features="{" ".join(b[5])}"><svg class="ic" width="20" height="20" aria-hidden="true"><use href="#{ids}-{b[3]}"/></svg>'
                     f'<span class="kn">{ESC(b[1])}</span><span class="kw">{ESC(" ".join(who))}</span></li>')
    return '<ol class="worlds-key" aria-label="Blocks of work">' + "".join(items) + "</ol>"


def worlds_block(side, tools, devices, intro):
    """The two-worlds visual of one side, all devices: ``devices`` = [(slug, name, card line, feature table)]. The first
    device shows; the page's device switch shows the others (js/visuals.js). ``tools`` = [(name, css var)]."""
    ids = f"wic-{side}"
    keys = sorted(set([b[3] for b in V.BLOCKS]))
    out = [f'<div class="worlds" data-side="{side}">', sprite(ids, keys)]
    out.append('<div class="worlds-legend" role="group" aria-label="Tools">')
    for t, var in tools:
        out.append(f'<button type="button" class="worlds-leg" data-tool="{ESC(t, quote=True)}" aria-pressed="false" aria-label="{ESC(t, quote=True)}" style="--c:var({var})">'
                   f'<span class="chip"><span class="mono">{ESC(V.MONO.get(t, t))}</span></span><span class="nm">{ESC(t)}</span></button>')
    out.append("</div>")
    out.append('<p class="worlds-status" aria-live="polite"></p>')
    out.append('<div class="worlds-stage">')
    jsons = {}
    lay_w = V.WORLDS_LAYOUT["wide" if side == "gpu" else "wide_cpu"]
    lay_n = V.narrow_layout(side, **{k: V.NARROW[k] for k in ("sx", "sy", "node", "icon", "pad_scale", "size")})
    for i, (slug, name, card, table) in enumerate(devices):
        Wd = cached_worlds(table, tools, side + "-wide", lay_w)
        Wn = cached_worlds(table, tools, side + "-narrow", lay_n)
        aria = f"Two worlds on {name}: " + "; ".join(
            f"{t} covers {len(V.covered_blocks(table, t))} of {len(V.BLOCKS)} blocks" for t, _v in tools)
        out.append(f'<div class="worlds-dev" data-slug="{ESC(slug, quote=True)}"{"" if i == 0 else " hidden"}>')
        out.append(f'<div class="worlds-wide">{worlds_svg(Wd, ids, f"{side}{i}w", aria)}</div>')
        out.append(f'<div class="worlds-narrow">{worlds_svg(Wn, ids, f"{side}{i}n", aria)}{key_list(Wn, ids)}</div>')
        out.append(f'<p class="axis-note worlds-caption">Two worlds on {ESC(card)}.</p>')
        out.append('<details class="radar-data worlds-data"><summary>Show the data behind the two worlds</summary>'
                   + worlds_tables(table, [t for t, _v in tools]) + "</details></div>")
        jsons[slug] = worlds_json(table, [t for t, _v in tools])
    out.append('<div class="worlds-pop" role="tooltip" hidden></div></div>')
    out.append(f'<p class="axis-note worlds-note">{intro}</p>')
    out.append('<script type="application/json" class="worlds-json">' + json.dumps({"side": side, "devices": jsons}, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>")
    out.append("</div>")
    return "\n".join(out)


# --------------------------------------------------------------------------- the rosette
def _wedge(R, a0, a1, narrow):
    cx, cy = R.cx, R.cy
    if narrow:
        return (f"M{cx} {cy}L{V.pol(cx, cy, R.RW1, a0)[0]:.1f} {V.pol(cx, cy, R.RW1, a0)[1]:.1f}"
                + V.arc_path(cx, cy, R.RW1, a0, a1).replace("M", "L", 1) + "Z")
    return (f"M{V.pol(cx, cy, R.RW0, a0)[0]:.1f} {V.pol(cx, cy, R.RW0, a0)[1]:.1f}L{V.pol(cx, cy, R.RW1, a0)[0]:.1f} {V.pol(cx, cy, R.RW1, a0)[1]:.1f}"
            + V.arc_path(cx, cy, R.RW1, a0, a1).replace("M", "L", 1) + f"L{V.pol(cx, cy, R.RW0, a1)[0]:.1f} {V.pol(cx, cy, R.RW0, a1)[1]:.1f}"
            + V.arc_path(cx, cy, R.RW0, a1, a0).replace("M", "L", 1) + "Z")


def _wrap(text, size, limit, bold=False):
    lines, cur = [], ""
    for word in text.split():
        nxt = f"{cur} {word}".strip()
        if cur and V.text_width(nxt, size, bold) > limit:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + [cur]


def rosette_svg(R, ids, aria, name, stamp):
    """One `V.Rosette` as SVG: the wedges, each tool's bands, the feature nodes and labels, the sector names, the centre."""
    narrow = R.mode == "narrow"
    out = [f'<svg class="rosette-svg {"rosette-svg-narrow" if narrow else "rosette-svg-wide"}" viewBox="0 0 {R.W} {R.H}" role="group" aria-label="{ESC(aria, quote=True)}">']
    for i, sk in enumerate(R.sect):
        a0, a1 = R.sect[sk]
        out.append(f'<path class="wedge{" alt" if i % 2 else ""}" data-sector="{sk}" d="{_wedge(R, a0, a1, narrow)}"/>')
    for tool, chain, rr, _pts in R.bands:
        out.append(f'<path class="blob band" data-tool="{ESC(tool, quote=True)}" data-sector="{V.SECTOR_OF[chain[0]]}" data-features="{" ".join(chain)}" style="--c:var({R.vars[tool]})" d="{R.band_path(chain, rr)}"/>')
    for f in R.features:
        x, y = R.node_xy[f]
        who = [t for t in R.tools if R.covered(f, t)]
        q = f not in V.MEASURED
        out.append(f'<g class="rnode" data-feature="{f}" data-sector="{V.SECTOR_OF[f]}" tabindex="0" role="button" aria-label="{ESC(V.LABEL[f])}: '
                   f'{ESC(", ".join(who)) if who else "no tool"} covers it">'
                   f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="{R.NR + 6}"/><circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="{R.NR}"/>'
                   + _arcs(x, y, R.NR + 1.5, who, R.tools, R.vars) + icon_g(ids, f, x, y, R.ISZ) + "</g>")
        lab = R.labels[f]
        out.append(f'<text class="nlabel{" q" if q else ""}" data-feature="{f}" data-sector="{V.SECTOR_OF[f]}" text-anchor="{lab["anchor"]}" x="{lab["x"]:.1f}" y="{lab["y"]:.1f}">'
                   + _tspans(lab["x"], lab["lines"], R.lh) + "</text>")
    if not narrow:
        for sk, nm in R.names.items():
            q = all(f not in V.MEASURED for f in SECTOR_FEATURES[sk])
            ix, iy, isz = nm["icon"]
            out.append(f'<g class="rsector" data-sector="{sk}" tabindex="0" role="button" aria-label="{ESC(" ".join(nm["lines"]))}: focus this sector">'
                       + icon_g(ids, V.SECTOR[sk][3], ix, iy, isz)
                       + f'<text class="slabel{" q" if q else ""}" text-anchor="{nm["anchor"]}" x="{nm["x"]:.1f}" y="{nm["y"]:.1f}">'
                       + _tspans(nm["x"], nm["lines"], nm["lh"]) + "</text></g>")
        cl = _wrap(name, 14, 200, True)
        y0 = R.cy - 10 - (len(cl) - 1) * 9
        out.append(f'<text class="centre h" x="{R.cx}" y="{y0:.1f}">' + _tspans(R.cx, cl, 17) + "</text>")
        yy = y0 + len(cl) * 17 + 2
        out.append(f'<text class="centre" x="{R.cx}" y="{yy:.1f}">{ESC(stamp)}' + _tspans(R.cx, ["bands: within 2× of the best,", "or 4 of 5 in the rubric"], 16, 18) + "</text>")
    else:
        sk = R.sector
        out.append(f'<text class="slabel" data-sector="{sk}" text-anchor="middle" x="{R.cx}" y="{R.cy + 30}">{ESC(" ".join(V.SECTOR[sk][1]))}</text>')
        out.append(f'<text class="centre" x="{R.cx}" y="{R.cy + 48}">' + _tspans(R.cx, _wrap(name, 11, 220), 14) + "</text>")
    out.append("</svg>")
    return "".join(out)


SECTOR_FEATURES = {s[0]: s[2] for s in V.SECTORS}


def rosette_block(side, tools, devices, intro):
    """The rosette of one side, all devices: wide (every sector) and phone width (one sector at a time under a picker of
    sector icons). ``devices`` as in `worlds_block`, plus a date stamp as the fifth item."""
    ids = f"ric-{side}"
    keys = sorted(set(k for k, _l, _m in V.FEATURES) | set(s[3] for s in V.SECTORS))
    out = [f'<div class="rosette" data-side="{side}">', sprite(ids, keys)]
    out.append('<div class="worlds-legend" role="group" aria-label="Tools">')
    for t, var in tools:
        out.append(f'<button type="button" class="worlds-leg" data-tool="{ESC(t, quote=True)}" aria-pressed="false" aria-label="{ESC(t, quote=True)}" style="--c:var({var})">'
                   f'<span class="chip"><span class="mono">{ESC(V.MONO.get(t, t))}</span></span><span class="nm">{ESC(t)}</span></button>')
    out.append("</div>")
    out.append('<p class="worlds-status" aria-live="polite"></p>')
    out.append('<div class="worlds-stage">')
    jsons = {}
    for i, (slug, name, card, table, stamp) in enumerate(devices):
        aria = f"Rosette on {name}: every radar axis fanned open, each tool's band over the features it covers"
        out.append(f'<div class="worlds-dev rosette-dev" data-slug="{ESC(slug, quote=True)}"{"" if i == 0 else " hidden"}>')
        out.append(f'<div class="worlds-wide">{rosette_svg(cached_rosette(table, tools, "wide"), ids, aria, name, stamp)}</div>')
        out.append('<div class="worlds-narrow"><div class="rosette-picker" role="group" aria-label="Sector">')
        for sk, lines, _f, icon in V.SECTORS:
            out.append(f'<button type="button" class="pick{" on" if sk == "ensemble" else ""}" data-sector="{sk}" aria-pressed="{"true" if sk == "ensemble" else "false"}" '
                       f'aria-label="{ESC(" ".join(lines))}"><svg class="ic" width="20" height="20" aria-hidden="true"><use href="#{ids}-{icon}"/></svg></button>')
        out.append("</div>")
        for sk, _l, _f, _i in V.SECTORS:
            out.append(f'<div class="rosette-sector" data-sector="{sk}"{"" if sk == "ensemble" else " hidden"}>'
                       + rosette_svg(cached_rosette(table, tools, "narrow", sk), ids, aria + " (" + " ".join(V.SECTOR[sk][1]) + ")", name, stamp) + "</div>")
        out.append("</div>")
        out.append(f'<p class="axis-note worlds-caption">Rosette on {ESC(card)}.</p>')
        out.append('<details class="radar-data worlds-data"><summary>Show the data behind the rosette</summary>'
                   + worlds_tables(table, [t for t, _v in tools]).split("</table>", 1)[1] + "</details></div>")
        jsons[slug] = worlds_json(table, [t for t, _v in tools])
    out.append("</div>")
    out.append(f'<p class="axis-note worlds-note">{intro}</p>')
    out.append('<script type="application/json" class="worlds-json">' + json.dumps({"side": side, "devices": jsons}, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>")
    out.append("</div>")
    return "\n".join(out)
