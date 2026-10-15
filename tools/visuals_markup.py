# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Markup of the two coverage visuals (see visuals.py): the capability map and the rosette, as inline SVG plus the data
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


def cached_rosette(table, tools, mode, sector="ensemble"):
    key = ("r", mode, sector, tuple(t[0] for t in tools), _signature(table, [t[0] for t in tools]))
    if key not in _CACHE:
        _CACHE[key] = V.Rosette(table, tools, mode, sector)
    return _CACHE[key]


# --------------------------------------------------------------------------- the capability map
#: The summary line when no tool is selected (the chart shows every capability as a neutral dot on the centre line).
NONE_SENTENCE = "Pick a tool to see where each capability runs."


def _link(href, text, cls=""):
    return f'<a{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} href="{ESC(href, quote=True)}">{ESC(text)}</a>'


def cq_svg(Q, ids, uid, tool, aria):
    """The chart in one width: a soft Simulation-to-AI gradient, the three bands with their names on the left edge, the
    middle band's faint grid, and one icon per capability (ring, glyph, two-line name) placed at the selected tool's state."""
    c = Q.c
    W, H = c["W"], Q.H
    x0, x1 = c["L"], W - c["R"]
    out = [f'<svg class="cq-svg cq-{Q.mode}" data-mode="{Q.mode}" viewBox="0 0 {W} {H:.0f}" role="img" aria-label="{ESC(aria, quote=True)}">']
    out.append(f'<defs><linearGradient id="cqg-{uid}" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="var(--cm-sim)" stop-opacity=".30"/>'
               f'<stop offset="1" stop-color="var(--cm-ai)" stop-opacity=".22"/></linearGradient></defs>')
    out.append(f'<rect class="cq-bg" x="{x0}" y="{c["head"] - 4}" width="{x1 - x0}" height="{H - c["head"] - 2:.0f}" rx="12" fill="url(#cqg-{uid})"/>')
    out.append(f'<text class="cq-head" x="{x0 + 10}" y="{c["head"] - 12}" style="font-size:{c["fs"] + 3}px">Simulation</text>'
               f'<text class="cq-head" text-anchor="end" x="{x1 - 10}" y="{c["head"] - 12}" style="font-size:{c["fs"] + 3}px">AI</text>')
    for bnd in V.BANDS:
        t, z = Q.band[bnd]
        out.append(f'<rect class="cq-band cq-band-{bnd}" x="{x0}" y="{t:.1f}" width="{x1 - x0}" height="{z - t:.1f}"/>')
        mid = (t + z) / 2
        words = V.BAND_NAME[bnd].split(" and ") if Q.mode == "narrow" and bnd == "mid" else [V.BAND_NAME[bnd]]
        lines = [words[0] + (" and" if len(words) > 1 else "")] + ([words[1]] if len(words) > 1 else [])
        out.append(f'<text class="cq-axis" data-band="{bnd}" text-anchor="end" x="{x0 - 8}" y="{mid - (len(lines) - 1) * 6 + 4:.1f}" style="font-size:{c["fs"] + 1}px">'
                   + "".join(f'<tspan x="{x0 - 8}" dy="{0 if i == 0 else 12}">{ESC(l)}</tspan>' for i, l in enumerate(lines)) + "</text>")
    mt, mz = Q.band["mid"]
    for f in (0.25, 0.5, 0.75):
        gx = Q.x0 + f * (Q.x1 - Q.x0)
        out.append(f'<line class="cq-grid" x1="{gx:.1f}" y1="{mt + 3:.1f}" x2="{gx:.1f}" y2="{mz - 3:.1f}"/>')
    for r in range(1, Q.nrows["mid"]):
        gy = mt + c["pad"] + r * Q.pitch - 2
        out.append(f'<line class="cq-grid" x1="{x0 + 4}" y1="{gy:.1f}" x2="{x1 - 4}" y2="{gy:.1f}"/>')
    isz = round(c["icon"] * 0.62, 1)
    for k in V.BLOCKS_KEYS:
        p = Q.pos[tool][k]
        b = V.BLOCK[k]
        r = c["icon"] / 2
        lab = "".join(f'<tspan x="0" dy="{c["fs"] * 0.95 if i == 0 else c["lh"]:.1f}">{ESC(l)}</tspan>' for i, l in enumerate(b[2]))
        out.append(f'<g class="cq-ic is-{p["kind"]}" data-block="{k}" data-x="{Q.caps.xs[k]}" data-y="{"" if Q.caps.y(tool, k) is None else Q.caps.y(tool, k)}" '
                   f'style="transform:translate({p["x"]:.1f}px,{p["y"]:.1f}px)">'
                   f'<circle class="cq-ring" r="{r}"/><g class="ic" transform="translate({-isz / 2} {-isz / 2})"><use href="#{ids}-{b[3]}" width="{isz}" height="{isz}"/></g>'
                   f'<text class="cq-lab" text-anchor="middle" x="0" y="{r + c["gap"]:.1f}">{lab}</text></g>')
    out.append("</svg>")
    return "".join(out)


def cm_list(caps, tool):
    """The selected tool's own list: each covered capability with its CPU and GPU ticks (each a link to its source) and
    the one-line note, then one greyed line naming what the tool does not cover first-class."""
    items, none = [], []
    for key in V.BLOCKS_KEYS:
        if not caps.stop(tool, key):
            none.append(V.BLOCK[key][1])
            continue
        ticks, notes = [], []
        for dev, name in V.DEVICES:
            c = caps.cell(tool, key, dev)
            if c["covered"]:
                ticks.append(_link(c["source"], f"{name} \u2713", "cm-tick"))
                if c["note"] not in notes:
                    notes.append(c["note"])
            else:
                ticks.append(f'<span class="cm-tick is-no">{name} \u2013</span>')
        items.append(f'<li data-block="{key}"><span class="cm-ln">{ESC(V.BLOCK[key][1])}</span> <span class="cm-ticks">{" ".join(ticks)}</span> '
                     f'<span class="cm-note">{ESC(" ".join(notes))}</span></li>')
    grey = f'<p class="cm-grey">Not first-class: {ESC(", ".join(none))}.</p>' if none else ""
    return f'<ul class="cm-list">{"".join(items)}</ul>{grey}'


def cm_compare(caps, tools):
    """Every tool side by side: capabilities as rows, tools as columns; each cell CPU, GPU, both or empty, with its sources."""
    head = "".join(f'<th scope="col">{ESC(t)}</th>' for t, _v in tools)
    rows = []
    for key in V.BLOCKS_KEYS:
        cells = []
        for t, _v in tools:
            st = caps.stop(t, key)
            if not st:
                cells.append('<td data-stop="none"></td>')
                continue
            devs = [d for d, _n in V.DEVICES if caps.covered(t, key, d)]
            srcs = [caps.cell(t, key, d)["source"] for d in devs]
            if len(set(srcs)) == 1:
                inner = _link(srcs[0], V.STOP_NAME[st])
            else:
                inner = ESC(V.STOP_NAME[st]) + " " + " ".join(_link(s_, V.DEVICE_NAME[d], "cm-also") for d, s_ in zip(devs, srcs))
            cells.append(f'<td data-stop="{st}">{inner}</td>')
        rows.append(f'<tr data-block="{key}"><th scope="row">{ESC(V.BLOCK[key][1])}</th>{"".join(cells)}</tr>')
    return ('<details class="cm-compare"><summary>Compare all tools</summary><div class="cm-scroll" tabindex="0" role="region" aria-label="All tools, side by side">'
            '<table class="cm-table"><caption>Where each tool has a documented, first-class way to do each capability: CPU, GPU or both. '
            'An empty cell is not first-class. Every filled cell links to its source.</caption>'
            f'<thead><tr><th scope="col">Capability</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')


def capmap_json(caps, tools, charts):
    """What the script reads: for each width, the chart's size, bands and every tool's icon positions (and the no-tool strip)."""
    return {"tools": [t for t, _v in tools], "modes": {m: q.json() for m, q in charts.items()},
            "x": {k: caps.xs[k] for k in V.BLOCKS_KEYS},
            "y": {t: {k: caps.y(t, k) for k in V.BLOCKS_KEYS} for t, _v in tools}}


def capmap_block(side, caps, tools, intro, caption, default="raptor"):
    """The capability chart, the same on every device: a tool picker (tap the chosen tool again to pick none), the chart (a wide
    and a phone-width drawing), the selected tool's sentence and list, the comparison table and the JSON the script reads.
    Everything the default tool shows is in the page; the script only switches tools. ``side`` namespaces the ids (one copy per
    hardware panel). ``tools`` = [(name, css var)]."""
    var = dict(tools)
    ids = f"wic-{side}"
    out = [f'<div class="capmap" data-side="{side}" data-tool="{ESC(default, quote=True)}" style="--c:var({var[default]})">', V_sprite(ids)]
    out.append('<div class="cm-chips" role="group" aria-label="Tool">')
    for t, v in tools:
        on = t == default
        out.append(f'<button type="button" class="cm-chip{" is-on" if on else ""}" data-tool="{ESC(t, quote=True)}" '
                   f'aria-pressed="{"true" if on else "false"}" style="--c:var({v})">'
                   f'<span class="chip"></span><span class="nm">{ESC(t)}</span></button>')
    out.append("</div>")
    charts = {m: V.QuadChart(caps, m) for m in V.QUAD_MODES}
    aria = ("Where each capability sits: Simulation to AI across, CPU, CPU and GPU, or GPU down. Pick a tool and its capabilities "
            "light up; the list under the chart gives the same facts as text.")
    out.append('<div class="cm-chart">')
    for m, q in charts.items():
        out.append(f'<div class="cq-{m}-box">{cq_svg(q, ids, side + m, default, aria)}</div>')
    out.append("</div>")
    out.append('<p class="cm-legend"><span class="cm-key"><span class="cm-dot-on"></span>first-class: a glowing icon with its name</span> '
               '<span class="cm-key"><span class="cm-dot-off"></span>not first-class: a faint icon on the middle band, no name</span></p>')
    out.append(f'<p class="cm-summary" aria-live="polite" data-none="{ESC(NONE_SENTENCE, quote=True)}">{ESC(caps.summary(default))}</p>')
    for t, _v in tools:
        out.append(f'<div class="cm-tool" data-tool="{ESC(t, quote=True)}"{"" if t == default else " hidden"}>{cm_list(caps, t)}</div>')
    out.append(cm_compare(caps, tools))
    out.append(f'<p class="axis-note cm-caption">{caption}</p>')
    out.append(f'<p class="axis-note cm-note-text">{intro}</p>')
    j = dict(capmap_json(caps, tools, charts), side=side, summaries={t: caps.summary(t) for t, _v in tools}, none=NONE_SENTENCE)
    out.append('<script type="application/json" class="cm-json">' + json.dumps(j, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>")
    out.append("</div>")
    return "\n".join(out)


def V_sprite(ids):
    return sprite(ids, sorted(set(b[3] for b in V.BLOCKS)))


# --------------------------------------------------------------------------- the feature tables (rosette)
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


def feature_json(table, tools):
    """What the rosette's popover shows for each feature, in the table's own words."""
    vals = {}
    for f, _l, _m, cells in feature_rows(table, tools):
        measured = f in V.MEASURED
        vals[f] = {t: ([c[0], c[1] if measured else "", 1 if c[2] else 0] if c[0] is not None else None) for t, c in cells.items()}
    return {"vals": vals}


def feature_table(table, tools):
    """Every feature's reading per tool, with whether it meets the radar's rule."""
    th = "".join(f'<th scope="col">{ESC(t)}</th>' for t in tools)
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
    return (f'<table class="worlds-table worlds-features"><caption>Features: measured readings, and the rubric scores (judgement). A tick marks '
            f'a feature the tool covers: within {V.WITHIN:g}× of the best tool, or {V.RUBRIC_MIN} of 5</caption>'
            f'<thead><tr><th scope="col">Feature</th>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


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
    sector icons). ``devices`` = [(slug, name, card line, feature table, date stamp)]."""
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
                   + feature_table(table, [t for t, _v in tools]) + "</details></div>")
        jsons[slug] = feature_json(table, [t for t, _v in tools])
    out.append("</div>")
    out.append(f'<p class="axis-note worlds-note">{intro}</p>')
    out.append('<script type="application/json" class="worlds-json">' + json.dumps({"side": side, "devices": jsons}, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>")
    out.append("</div>")
    return "\n".join(out)
