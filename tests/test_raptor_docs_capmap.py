# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The capability-map SVG: self-contained, byte-stable, one covered square per covered cell of the site's data."""
import json
import re
import unittest
import xml.etree.ElementTree as ET

from raptor_docs_fixture import SITE_ROOT
from raptor_docs import capmap, themed_svg


def contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Capmap(unittest.TestCase):
    svg = capmap.render(SITE_ROOT)

    def test_two_renders_are_identical(self):
        self.assertEqual(self.svg, capmap.render(SITE_ROOT))

    def test_it_is_one_self_contained_svg(self):
        root = ET.fromstring(self.svg)
        self.assertTrue(root.tag.endswith("}svg"))
        self.assertNotRegex(self.svg, r"<script|<a |href=|<image|<use|url\(|@import|https?://(?!www\.w3\.org)")

    def test_filled_squares_equal_the_covered_cells(self):
        data = json.loads((SITE_ROOT / "_data" / "capabilities.json").read_text())
        covered = sum(bool(data["cells"][t][b][d]["covered"]) for t in data["tools"] for b in data["blocks"] for d in data["devices"])
        self.assertEqual(len(re.findall(r'class="on"', self.svg)), covered)
        self.assertEqual(len(re.findall(r"<rect", self.svg)), len(data["tools"]) * len(data["blocks"]) * len(data["devices"]))

    def test_the_pair_has_fixed_colours_and_no_media_query(self):
        dark = capmap.render(SITE_ROOT, themed_svg.DARK)
        for text in (self.svg, dark):
            self.assertNotIn("prefers-color-scheme", text)
        self.assertIn(themed_svg.LIGHT["ink"], self.svg)
        self.assertIn(themed_svg.DARK["ink"], dark)
        self.assertNotIn(themed_svg.LIGHT["ink"], dark)

    def test_ink_reads_on_both_surfaces(self):
        for pal in (themed_svg.LIGHT, themed_svg.DARK):
            for key in ("ink", "sub"):
                self.assertGreaterEqual(contrast(pal[key], pal["bg"]), 4.5, (key, pal[key]))
            self.assertGreaterEqual(contrast(pal["on"], pal["bg"]), 3.0)

    def test_check_mode_reds_on_a_stale_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = f"{tmp}/m.svg"
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out]), 0)
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out, "--check"]), 0)
            with open(out, "a") as f:
                f.write(" ")
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out, "--check"]), 1)
            capmap.main(["--site", str(SITE_ROOT), "-o", out])
            with open(f"{tmp}/m-dark.svg", "a") as f:  # the dark half is checked too
                f.write(" ")
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out, "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
