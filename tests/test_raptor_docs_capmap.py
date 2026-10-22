# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The capability-map SVG: self-contained, byte-stable, one covered square per covered cell of the site's data."""
import json
import re
import unittest
import xml.etree.ElementTree as ET

from raptor_docs_fixture import SITE_ROOT
from raptor_docs import capmap


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

    def test_check_mode_reds_on_a_stale_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = f"{tmp}/m.svg"
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out]), 0)
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out, "--check"]), 0)
            open(out, "a").write(" ")
            self.assertEqual(capmap.main(["--site", str(SITE_ROOT), "-o", out, "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
