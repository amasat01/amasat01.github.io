# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The tool palette, read from the one place that defines it: the token block in ``_static/custom.css``.

Generators that draw a tool in a figure (``generate_what_you_write_svg.py``) take its colour from here
instead of spelling a hex, so the figures, the charts and the radars always agree.
"""
import pathlib
import re

CSS = pathlib.Path(__file__).resolve().parent.parent / "_static" / "custom.css"
TOOLS = ("raptor", "warp", "jax", "pytorch", "cupy", "numba", "numpy")


def tool_palette(theme):
    """{tool: "#rrggbb"} for ``theme`` ("light" | "dark")."""
    css = CSS.read_text()
    start = css.index("The tool palette")
    pattern = (r':root, html\[data-theme="light"\] \{([^}]*)\}' if theme == "light"
               else r'html\[data-theme="dark"\] \{([^}]*)\}')
    block = re.search(pattern, css[start:]).group(1)
    return {t: re.search(rf"--tool-{t}: (#[0-9a-f]{{6}})", block).group(1) for t in TOOLS}
