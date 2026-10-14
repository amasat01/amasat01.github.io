# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""No tool colour is spelled anywhere but the token block of _static/custom.css.

The palette lives in one place; charts, radars and figures reach it through ``var(--tool-*)`` or
``tools/palette.py``. This test greps the site's own sources for a hard-coded tool colour -- the
current palette's hex values and the legacy brand values earlier versions typed by hand -- and
allows the token block only. The generated SVG figures carry the palette as output: they must match
the tokens exactly (checked below), never carry another tool colour.
"""
import pathlib
import re
import sys
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))
from palette import tool_palette  # noqa: E402

#: Tool colours typed by hand before the shared palette (brand and earlier palettes).
LEGACY = ("#ee4c2c", "#1a9a8c", "#00a3e0", "#518d05", "#306101", "#4d77cf", "#76b900", "#88e97e", "#7ea3f2",
          "#218048", "#199c98", "#ab3b22", "#af7f2b", "#1f5c7c", "#342cdb", "#b4f5a0", "#0dffd4", "#e76858",
          "#e0bf66", "#81c5ea", "#8999f1")
SKIP_DIRS = {"_build", ".git", "__pycache__", "tests", "notebooks"}
#: Generated figures that draw tools: they are checked against the tokens, not scanned.
GENERATED_FIGURES = {"what_you_write_light.svg", "what_you_write_dark.svg"}


def _sources():
    for p in sorted(SITE_ROOT.rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(SITE_ROOT).parts):
            continue
        if p.suffix in {".py", ".md", ".css", ".js", ".html", ".svg", ".json", ".yml"} and p.name not in GENERATED_FIGURES:
            yield p


def _without_token_block(text):
    start = text.index("The tool palette")
    end = text.index("/* ---- Typography")
    return text[:start] + text[end:]


class NoHardCodedToolColours(unittest.TestCase):
    def test_no_tool_colour_outside_the_token_block(self):
        banned = set(LEGACY)
        for theme in ("light", "dark"):
            banned |= {v.lower() for v in tool_palette(theme).values()}
        # the raptor family purple is also the site's own mark colour: it may appear as such
        banned -= {"#7d53dc", "#9269f5"}
        found = []
        for p in _sources():
            text = p.read_text(errors="ignore")
            if p.name == "custom.css":
                text = _without_token_block(text)
            low = text.lower()
            for h in banned:
                for m in re.finditer(re.escape(h), low):
                    found.append(f"{p.relative_to(SITE_ROOT)}:{low.count(chr(10), 0, m.start()) + 1} {h}")
        self.assertEqual(found, [], "hard-coded tool colours: " + "; ".join(found[:10]))

    def test_generated_figures_use_exactly_the_tokens(self):
        for theme in ("light", "dark"):
            pal = tool_palette(theme)
            svg = (SITE_ROOT / "_static" / "figures" / f"what_you_write_{theme}.svg").read_text().lower()
            self.assertIn(pal["warp"].lower(), svg)
            self.assertIn(pal["raptor"].lower(), svg)
            for h in LEGACY:
                self.assertNotIn(h, svg)


if __name__ == "__main__":
    unittest.main()
