# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Markup of the capability chart (see visuals.py), as inline SVG plus the data tables and the JSON the script reads. No dependency on the
site; styled by the classes in custom.css and driven by js/visuals.js."""
import html
import json

import radar_icons
import visuals as V

ESC = html.escape


def sprite(ids, keys):
    """The hidden ``<symbol>`` sheet the chart's icons are drawn from (inline, no external files)."""
    syms = "".join(f'<symbol id="{ids}-{k}" viewBox="0 0 24 24">{radar_icons.ICONS[k]}</symbol>' for k in keys)
    return f'<svg class="vis-icons" width="0" height="0" aria-hidden="true" focusable="false"><defs>{syms}</defs></svg>'


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
        gy = mt + c["pad"] + r * Q.pitch - c["vpad"] / 2
        out.append(f'<line class="cq-grid" x1="{x0 + 4}" y1="{gy:.1f}" x2="{x1 - 4}" y2="{gy:.1f}"/>')
    isz = round(c["icon"] * 0.62, 1)
    for k in V.BLOCKS_KEYS:
        p = Q.pos[tool][k]
        b = V.BLOCK[k]
        r = c["icon"] / 2
        n = len(b[2])
        right = Q.side[k] == "r"
        lx = r + c["gap"] if right else -(r + c["gap"])
        y0 = -(n - 1) * c["lh"] / 2 + 0.35 * c["fs"]
        lab = "".join(f'<tspan x="{lx:.1f}" dy="{0 if i == 0 else c["lh"]}">{ESC(l)}</tspan>' for i, l in enumerate(b[2]))
        out.append(f'<g class="cq-ic is-{p["kind"]}" data-block="{k}" data-x="{Q.caps.xs[k]}" data-y="{"" if Q.caps.y(tool, k) is None else Q.caps.y(tool, k)}" '
                   f'tabindex="0" role="button" aria-haspopup="true" aria-expanded="false" aria-label="{ESC(b[1], quote=True)}: details" '
                   f'style="transform:translate({p["x"]:.1f}px,{p["y"]:.1f}px)">'
                   f'<circle class="cq-hit" r="{r + 5}"/>'
                   f'<circle class="cq-ring" r="{r}"/><g class="ic" transform="translate({-isz / 2} {-isz / 2})"><use href="#{ids}-{b[3]}" width="{isz}" height="{isz}"/></g>'
                   f'<text class="cq-lab" text-anchor="{"start" if right else "end"}" x="{lx:.1f}" y="{y0:.2f}" style="font-size:{c["fs"]}px">{lab}</text></g>')
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


def cards_json(caps, tools):
    """What the details card shows, per capability: its name, what counts, and for every tool the CPU and GPU cells
    ({c: covered, n: the note, s: the source link when covered})."""
    out = {}
    for k in V.BLOCKS_KEYS:
        per = {}
        for t, _v in tools:
            per[t] = {d: dict({"c": caps.covered(t, k, d), "n": caps.cell(t, k, d)["note"]}, **({"s": caps.cell(t, k, d)["source"]} if caps.covered(t, k, d) else {}))
                      for d, _n in V.DEVICES}
        out[k] = {"l": V.BLOCK[k][1], "needs": caps.needs[k], "t": per}
    return out


def capmap_json(caps, tools, charts):
    """What the script reads: for each width, the chart's size, bands and every tool's icon positions (and the no-tool strip)."""
    return {"tools": [t for t, _v in tools], "modes": {m: q.json() for m, q in charts.items()},
            "x": {k: caps.xs[k] for k in V.BLOCKS_KEYS}, "cards": cards_json(caps, tools),
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
    out.append('<div class="cq-card" role="group" aria-label="Capability details" hidden></div>')
    out.append("</div>")
    out.append('<p class="cm-legend"><span class="cm-key"><span class="cm-dot-on"></span>first-class: a glowing icon with its name</span> '
               '<span class="cm-key"><span class="cm-dot-off"></span>not first-class: a faint icon on the middle band, no name</span></p>')
    out.append(f'<p class="cm-summary" aria-live="polite" data-none="{ESC(NONE_SENTENCE, quote=True)}">{ESC(caps.summary(default))}</p>')
    out.append('<details class="cm-details"><summary>Show details</summary>')
    for t, _v in tools:
        out.append(f'<div class="cm-tool" data-tool="{ESC(t, quote=True)}"{"" if t == default else " hidden"}>{cm_list(caps, t)}</div>')
    out.append("</details>")
    out.append(cm_compare(caps, tools))
    out.append(f'<p class="axis-note cm-caption">{caption}</p>')
    out.append(f'<p class="axis-note cm-note-text">{intro}</p>')
    j = dict(capmap_json(caps, tools, charts), side=side, summaries={t: caps.summary(t) for t, _v in tools}, none=NONE_SENTENCE)
    out.append('<script type="application/json" class="cm-json">' + json.dumps(j, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>")
    out.append("</div>")
    return "\n".join(out)


def V_sprite(ids):
    return sprite(ids, sorted(set(b[3] for b in V.BLOCKS)))
