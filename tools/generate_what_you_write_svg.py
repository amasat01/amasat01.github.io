#!/usr/bin/env python3
# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Generate ``_static/figures/what_you_write_{light,dark}.svg``.

The figure is a fixed, two-column infographic ("what you write" -- Warp's
thread program next to a RAPTOR hawk kernel). Layout and palette are the
site's own; this script exists only so the CODE baked into the picture --
the RAPTOR panel's kernel body and its "who decides" gloss line -- is a
single source of truth instead of hand-edited SVG text. Re-run it whenever
that code changes; never hand-edit the two SVG files directly.

Usage::

    python tools/generate_what_you_write_svg.py [--out-dir _static/figures]
"""
from __future__ import annotations

import argparse
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# The RAPTOR panel's kernel body: one Mutable/Terminated plane read and
# written as a plain variable (sequential/tuple-assignment rules), the same
# kernel shown on the landing hero.
RAPTOR_CODE_COMMENT = "# the step's math"
RAPTOR_CODE_LINES = (
    "x, v = x + dt*v, v - dt*w*w*x",
    "t += dt",
    "terminated = t &gt;= t_end",
)
RAPTOR_LOOP_EXIT_GLOSS = "terminated = t &gt;= t_end"

THEMES = {
    "light": dict(
        suffix="",
        bg="#fcfcfb", caption="#52514e", heading="#0b0b0b",
        box_fill="#ffffff", box_stroke="#e1e0d9", divider="#e1e0d9",
        warp_accent="#9a6a00", raptor_accent="#6b3fc4",
        code_default="#0b0b0b", code_comment="#8f5902",
        code_keyword="#204a87", code_name="#0b0b0b", code_builtin="#5c35cc",
        code_number="#0000cf",
        pill_you_stroke="#898781", pill_you_text="#0b0b0b",
        pill_engine_fill="#6b3fc4", pill_engine_text="#0b0b0b",
        gloss="#52514e", legend_fill="#ffffff", legend_stroke="#e1e0d9",
    ),
    "dark": dict(
        suffix="-d",
        bg="#1a1a19", caption="#c3c2b7", heading="#ffffff",
        box_fill="#242422", box_stroke="#2c2c2a", divider="#2c2c2a",
        warp_accent="#edb94a", raptor_accent="#a88bf0",
        code_default="#f8f8f2", code_comment="#959077",
        code_keyword="#66d9ef", code_name="#a6e22e", code_builtin="#a6e22e",
        code_number="#ae81ff",
        pill_you_stroke="#898781", pill_you_text="#ffffff",
        pill_engine_fill="#a88bf0", pill_engine_text="#ffffff",
        gloss="#c3c2b7", legend_fill="#242422", legend_stroke="#2c2c2a",
    ),
}

PILL_ROWS = (
    ("loop &amp; exit", "while-loop exits in the kernel", RAPTOR_LOOP_EXIT_GLOSS, "you", "engine"),
    ("launch timing", "wp.launch(kernel, dim=n), once", "auto by default; eagle times it", "you", "engine"),
    ("compaction + reorder", "one launch; add it yourself", "drops finished samples, can reorder", "you", "engine"),
    ("graph capture", "wrap calls in wp.ScopedCapture", "eagle.simulate captures &amp; replays", "you", "engine"),
    ("CPU &amp; GPU", "pick the device per wp.launch call", "dispatches on the array's own type", "you", "engine"),
    ("derivatives", "record it with wp.Tape(), backward", "derives forward &amp; backward kernels", "you", "engine"),
)


def _code_line(x, y, spans):
    """One <text> with a run of <tspan>s: spans is [(text, fill_key_or_None), ...]."""
    body = "".join(
        f'<tspan x="{x}" fill="{{{fill}}}"{" font-weight=\"700\"" if bold else ""}'
        f'{" font-style=\"italic\"" if italic else ""}>{text}</tspan>'
        if i == 0 else
        f'<tspan fill="{{{fill}}}"{" font-weight=\"700\"" if bold else ""}'
        f'{" font-style=\"italic\"" if italic else ""}>{text}</tspan>'
        for i, (text, fill, bold, italic) in enumerate(spans)
    )
    return f'<text x="{x}" y="{y}" font-size="12" font-family="{MONO}">{body}</text>'


def _pill_pair(x_you, x_engine, y, label, you_gloss, engine_gloss, mono_gloss=False):
    gloss_font = f' font-family="{MONO}"' if mono_gloss else f' font-family="{SANS}"'
    out = []
    out.append(f'<rect x="{x_you}" y="{y}" width="34" height="17" rx="8.5" fill="none" '
               f'stroke="{{pill_you_stroke}}" stroke-width="1"/>')
    out.append(f'<text x="{x_you + 17}" y="{y + 12.5}" text-anchor="middle" font-size="12" '
               f'font-weight="600" fill="{{pill_you_text}}">you</text>')
    out.append(f'<text x="{x_you + 64}" y="{y + 12.5}" font-size="12" font-weight="600" '
               f'fill="{{pill_you_text}}">{label}</text>')
    out.append(f'<text x="{x_you + 64}" y="{y + 27}" font-size="12"{gloss_font} '
               f'fill="{{gloss}}">{you_gloss}</text>')
    return out


def render(theme_name: str) -> str:
    t = THEMES[theme_name]
    s = t["suffix"]

    warp_body = [
        ('<tspan x="30.0" fill="{code_builtin}" font-weight="700">@wp.kernel</tspan>',),
    ]

    def fmt(template: str) -> str:
        return template.format(**t)

    lines = []
    lines.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 570" width="100%" height="100%" '
        f'role="img" aria-labelledby="wyw-title{s} wyw-desc{s}" xml:space="preserve" font-family="{SANS}">'
    )
    lines.append(f'<title id="wyw-title{s}">What you write: Warp\'s thread program next to a RAPTOR (hawk) kernel</title>')
    lines.append(
        f'<desc id="wyw-desc{s}">Two side-by-side columns for the same batch-of-trajectories task, each '
        "sample stopping at its own time. Left, Warp: you write the thread program -- a tiny wp.kernel with "
        "a per-thread while-loop and its own exit test, launched once over all threads. Right, RAPTOR: you "
        "write one step of one sample -- a tiny hawk.kernel that writes the per-sample math as plain local "
        "variables and sets its own terminated flag; eagle.simulate drives the repeated launches. Below each "
        "code sketch, a list of six run-time decisions -- the per-sample loop and exit, launch timing, "
        "compaction and reorder, graph capture, running on CPU and GPU, and derivatives -- each tagged 'you' "
        "when the author writes it explicitly (true of every item in Warp's column, framed as control) or "
        "'engine' when eagle decides it at run time (true for launch timing, compaction, graph capture, "
        "CPU/GPU dispatch and generating derivatives in RAPTOR's column). Warp and RAPTOR both differentiate "
        "their kernels, Warp by recording a wp.Tape, RAPTOR by deriving forward- and backward-mode kernels "
        "from the same source. Code sketches are syntax-coloured to match this site's own code blocks.</desc>"
    )
    lines.append(fmt('<rect x="0" y="0" width="700" height="570" fill="{bg}"/>'))
    lines.append(fmt('<text x="350.0" y="16" text-anchor="middle" font-size="12" font-style="italic" '
                      'fill="{caption}">same task: a batch of trajectories, each sample stopping at its own time</text>'))

    # --- Warp column header ---
    lines.append(fmt('<text x="180.0" y="38" text-anchor="middle" font-size="16" font-weight="700" '
                      'fill="{heading}">Warp</text>'))
    lines.append(fmt('<text x="180.0" y="55" text-anchor="middle" font-size="12" fill="{caption}">'
                      'you write the thread program</text>'))
    lines.append(fmt('<rect x="20" y="61" width="320" height="3" fill="{warp_accent}"/>'))
    lines.append(fmt('<text x="20" y="81" font-size="12" font-weight="600" fill="{heading}">what you write</text>'))
    lines.append(fmt('<rect x="20" y="89" width="320" height="160" rx="8" fill="{box_fill}" '
                      'stroke="{box_stroke}" stroke-width="1"/>'))
    lines.append(fmt(f'<text x="30.0" y="108" font-size="12" font-family="{MONO}">'
                      '<tspan x="30.0" fill="{code_builtin}" font-weight="700">@wp.kernel</tspan></text>'))
    lines.append(fmt(f'<text x="30.0" y="124" font-size="12" font-family="{MONO}">'
                      '<tspan x="30.0" fill="{code_keyword}" font-weight="700">def</tspan>'
                      '<tspan fill="{code_name}"> oscillators</tspan>'
                      '<tspan fill="{code_default}">(x, v, k, ...):</tspan></text>'))
    lines.append(fmt(f'<text x="58.8" y="140" font-size="12" font-family="{MONO}">'
                      '<tspan x="58.8" fill="{code_default}">i = wp</tspan>'
                      '<tspan fill="{code_default}">.</tspan>'
                      '<tspan fill="{code_name}">tid</tspan>'
                      '<tspan fill="{code_default}">()</tspan></text>'))
    lines.append(fmt(f'<text x="58.8" y="156" font-size="12" font-family="{MONO}">'
                      '<tspan x="58.8" fill="{code_keyword}" font-weight="700">while</tspan>'
                      '<tspan fill="{code_default}"> ks &lt; ns:</tspan></text>'))
    lines.append(fmt(f'<text x="87.6" y="172" font-size="12" font-family="{MONO}">'
                      '<tspan x="87.6" fill="{code_comment}" font-style="italic"># ...RK4 math on xs, vs...</tspan></text>'))
    lines.append(fmt(f'<text x="87.6" y="188" font-size="12" font-family="{MONO}">'
                      '<tspan x="87.6" fill="{code_default}">ks += wp</tspan>'
                      '<tspan fill="{code_default}">.</tspan>'
                      '<tspan fill="{code_name}">float64</tspan>'
                      '<tspan fill="{code_default}">(</tspan>'
                      '<tspan fill="{code_number}" font-weight="700">1.0</tspan>'
                      '<tspan fill="{code_default}">)</tspan></text>'))
    lines.append(fmt(f'<text x="30.0" y="204" font-size="12" font-family="{MONO}">'
                      '<tspan x="30.0" fill="{code_comment}" font-style="italic"># run the batch:</tspan></text>'))
    lines.append(fmt(f'<text x="30.0" y="220" font-size="12" font-family="{MONO}">'
                      '<tspan x="30.0" fill="{code_default}">wp</tspan>'
                      '<tspan fill="{code_default}">.</tspan>'
                      '<tspan fill="{code_name}">launch</tspan>'
                      '<tspan fill="{code_default}">(oscillators, dim=n, ...)</tspan></text>'))
    lines.append(fmt('<text x="20" y="263" font-size="12" font-style="italic" fill="{caption}">'
                      "warp_kernel, condensed from eagle's perf_card.py</text>"))
    lines.append(fmt('<text x="20" y="288" font-size="12" font-weight="600" fill="{heading}">who decides</text>'))

    # --- RAPTOR column header ---
    lines.append(fmt('<text x="520.0" y="38" text-anchor="middle" font-size="16" font-weight="700" '
                      'fill="{heading}">RAPTOR</text>'))
    lines.append(fmt('<text x="520.0" y="55" text-anchor="middle" font-size="12" fill="{caption}">'
                      'you write one step of one sample</text>'))
    lines.append(fmt('<rect x="360" y="61" width="320" height="3" fill="{raptor_accent}"/>'))
    lines.append(fmt('<text x="360" y="81" font-size="12" font-weight="600" fill="{heading}">what you write</text>'))
    lines.append(fmt('<rect x="360" y="89" width="320" height="160" rx="8" fill="{box_fill}" '
                      'stroke="{box_stroke}" stroke-width="1"/>'))
    lines.append(fmt(f'<text x="370.0" y="108" font-size="12" font-family="{MONO}">'
                      '<tspan x="370.0" fill="{code_builtin}" font-weight="700">@hawk.kernel</tspan></text>'))
    lines.append(fmt(f'<text x="370.0" y="124" font-size="12" font-family="{MONO}">'
                      '<tspan x="370.0" fill="{code_keyword}" font-weight="700">def</tspan>'
                      '<tspan fill="{code_name}"> oscillator</tspan>'
                      '<tspan fill="{code_default}">(x, v, terminated, ...):</tspan></text>'))
    lines.append(fmt(f'<text x="398.8" y="140" font-size="12" font-family="{MONO}">'
                      f'<tspan x="398.8" fill="{{code_comment}}" font-style="italic">{RAPTOR_CODE_COMMENT}</tspan></text>'))
    body_ys = (156, 172, 188)
    for y, code in zip(body_ys, RAPTOR_CODE_LINES):
        lines.append(fmt(f'<text x="398.8" y="{y}" font-size="12" font-family="{MONO}">'
                          f'<tspan x="398.8" fill="{{code_default}}">{code}</tspan></text>'))
    lines.append(fmt(f'<text x="370.0" y="204" font-size="12" font-family="{MONO}">'
                      '<tspan x="370.0" fill="{code_comment}" font-style="italic"># run the batch:</tspan></text>'))
    lines.append(fmt(f'<text x="370.0" y="220" font-size="12" font-family="{MONO}">'
                      '<tspan x="370.0" fill="{code_default}">eagle</tspan>'
                      '<tspan fill="{code_default}">.</tspan>'
                      '<tspan fill="{code_name}">simulate</tspan>'
                      '<tspan fill="{code_default}">(oscillator, w=w,</tspan></text>'))
    lines.append(fmt(f'<text x="398.8" y="236" font-size="12" font-family="{MONO}">'
                      '<tspan x="398.8" fill="{code_default}">t_end=1.0, x=x, v=v, max_steps=S)</tspan></text>'))
    lines.append(fmt('<text x="360" y="263" font-size="12" font-style="italic" fill="{caption}">'
                      "oscillator + eagle.simulate, from the quickstart</text>"))
    lines.append(fmt('<text x="360" y="288" font-size="12" font-weight="600" fill="{heading}">who decides</text>'))

    lines.append(fmt('<line x1="350" y1="64" x2="350" y2="508" stroke="{divider}" stroke-width="1"/>'))

    # --- "who decides" pill rows, Warp (all "you") then RAPTOR (first "you", rest "engine") ---
    warp_glosses = [
        ("while-loop exits in the kernel", False),
        ("wp.launch(kernel, dim=n), once", False),
        ("one launch; add it yourself", False),
        ("wrap calls in wp.ScopedCapture", False),
        ("pick the device per wp.launch call", False),
        ("record it with wp.Tape(), backward", False),
    ]
    raptor_glosses = [
        (RAPTOR_LOOP_EXIT_GLOSS, True),
        ("auto by default; eagle times it", False),
        ("drops finished samples, can reorder", False),
        ("eagle.simulate captures &amp; replays", False),
        ("dispatches on the array's own type", False),
        ("derives forward &amp; backward kernels", False),
    ]
    labels = ("loop &amp; exit", "launch timing", "compaction + reorder", "graph capture", "CPU &amp; GPU", "derivatives")
    y0 = 298
    for i, (label, (gloss, mono)) in enumerate(zip(labels, warp_glosses)):
        y = y0 + 34 * i
        gloss_font = MONO if mono else SANS
        lines.append(fmt(f'<rect x="20" y="{y}" width="34" height="17" rx="8.5" fill="none" '
                          'stroke="{pill_you_stroke}" stroke-width="1"/>'))
        lines.append(fmt(f'<text x="37.0" y="{y + 12.5}" text-anchor="middle" font-size="12" '
                          'font-weight="600" fill="{heading}">you</text>'))
        lines.append(fmt(f'<text x="84" y="{y + 12.5}" font-size="12" font-weight="600" fill="{{heading}}">{label}</text>'))
        lines.append(fmt(f'<text x="84" y="{y + 27}" font-size="12" font-family="{gloss_font}" '
                          f'fill="{{gloss}}">{gloss}</text>'))

    for i, (label, (gloss, mono)) in enumerate(zip(labels, raptor_glosses)):
        y = y0 + 34 * i
        gloss_font = MONO if mono else SANS
        if i == 0:
            lines.append(fmt(f'<rect x="360" y="{y}" width="34" height="17" rx="8.5" fill="none" '
                              'stroke="{pill_you_stroke}" stroke-width="1"/>'))
            lines.append(fmt(f'<text x="377.0" y="{y + 12.5}" text-anchor="middle" font-size="12" '
                              'font-weight="600" fill="{heading}">you</text>'))
        else:
            lines.append(fmt(f'<rect x="360" y="{y}" width="56" height="17" rx="8.5" '
                              'fill="{raptor_accent}" fill-opacity="0.18" stroke="{raptor_accent}" stroke-width="1.25"/>'))
            lines.append(fmt(f'<text x="388.0" y="{y + 12.5}" text-anchor="middle" font-size="12" '
                              'font-weight="600" fill="{heading}">engine</text>'))
        lines.append(fmt(f'<text x="424" y="{y + 12.5}" font-size="12" font-weight="600" fill="{{heading}}">{label}</text>'))
        lines.append(fmt(f'<text x="424" y="{y + 27}" font-size="12" font-family="{gloss_font}" '
                          f'fill="{{gloss}}">{gloss}</text>'))

    # --- legend ---
    lines.append(fmt('<rect x="20" y="516" width="660" height="38" rx="8" fill="{legend_fill}" stroke="{legend_stroke}"/>'))
    lines.append(fmt('<rect x="34" y="528" width="34" height="17" rx="8.5" fill="none" stroke="{pill_you_stroke}" stroke-width="1"/>'))
    lines.append(fmt('<text x="51.0" y="540.5" text-anchor="middle" font-size="12" font-weight="600" fill="{heading}">you</text>'))
    lines.append(fmt('<text x="78" y="540" font-size="12" fill="{heading}">you write it, explicitly</text>'))
    lines.append(fmt('<rect x="320" y="528" width="56" height="17" rx="8.5" fill="{raptor_accent}" '
                      'fill-opacity="0.18" stroke="{raptor_accent}" stroke-width="1.25"/>'))
    lines.append(fmt('<text x="348.0" y="540.5" text-anchor="middle" font-size="12" font-weight="600" fill="{heading}">engine</text>'))
    lines.append(fmt('<text x="386" y="540" font-size="12" fill="{heading}">the engine decides it at run time</text>'))

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "_static" / "figures"))
    args = ap.parse_args(argv)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        out_path = out_dir / f"what_you_write_{theme}.svg"
        out_path.write_text(render(theme))
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
