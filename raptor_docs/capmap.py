# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The capability map as one self-contained SVG (no script, no link): a row per capability, a CPU and a GPU square per tool,
filled where the tool's own documentation shows a designed way to do it. Reads the site's ``_data/capabilities.json`` through
the site's ``tools/visuals.py`` (``Capabilities``), so it can never disagree with the site's chart.

    python -m raptor_docs.capmap [--site DIR] [-o FILE]     # write (default: print)
    python -m raptor_docs.capmap [--site DIR] -o FILE --check   # exit 1 if FILE differs from a fresh render

The site is ``--site``, else ``$RAPTOR_SITE``, else the checkout this package sits in.
"""
import argparse
import html
import importlib.util
import json
import os
import pathlib
import sys

LABEL_W, COL_W, ROW_H, HEAD_H, SQ = 250, 64, 22, 74, 14
STYLE = (".t{font:12px sans-serif;fill:#1b2433}.h{font:600 12px sans-serif;fill:#1b2433}.on{fill:#6d4aff}"
         ".off{fill:none;stroke:#aab4c8;stroke-width:1}.g{stroke:#e9edf5}"
         "@media (prefers-color-scheme:dark){.t,.h{fill:#e6ebf5}.on{fill:#a99bff}.off{stroke:#5b667c}.g{stroke:#2a3347}}")


def _capabilities(site):
    spec = importlib.util.spec_from_file_location("site_visuals", site / "tools" / "visuals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.Capabilities(json.loads((site / "_data" / "capabilities.json").read_text(encoding="utf-8")))


def render(site) -> str:
    vis, caps = _capabilities(pathlib.Path(site))
    width, height = LABEL_W + COL_W * len(caps.tools) + 40, HEAD_H + ROW_H * len(vis.BLOCKS) + 8
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
           f'aria-labelledby="t d"><title id="t">Capability map</title><desc id="d">Which tool has a documented way to do each block '
           f'of work, on the CPU (left square) and the GPU (right square).</desc><style>{STYLE}</style>']
    for j, tool in enumerate(caps.tools):
        x = LABEL_W + COL_W * j + COL_W // 2
        out.append(f'<text class="h" text-anchor="start" transform="translate({x} {HEAD_H - 8}) rotate(-35)">{html.escape(tool)}</text>')
    for i, block in enumerate(vis.BLOCKS):
        y = HEAD_H + ROW_H * i
        out.append(f'<line class="g" x1="0" x2="{width}" y1="{y}" y2="{y}"/>')
        out.append(f'<text class="t" x="4" y="{y + 15}">{html.escape(block[1])}</text>')
        for j, tool in enumerate(caps.tools):
            for k, (dev, _name) in enumerate(vis.DEVICES):
                x = LABEL_W + COL_W * j + (COL_W - 2 * SQ - 4) // 2 + k * (SQ + 4)
                cls = "on" if caps.covered(tool, block[0], dev) else "off"
                out.append(f'<rect class="{cls}" x="{x}" y="{y + 4}" width="{SQ}" height="{SQ}" rx="3"/>')
    return "\n".join(out) + "\n</svg>\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=os.environ.get("RAPTOR_SITE") or str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("-o", "--output")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    svg = render(args.site)
    if not args.output:
        sys.stdout.write(svg)
    elif args.check:
        path = pathlib.Path(args.output)
        if not path.is_file() or path.read_text(encoding="utf-8") != svg:
            print(f"capmap: {args.output} is out of date", file=sys.stderr)
            return 1
    else:
        pathlib.Path(args.output).write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
