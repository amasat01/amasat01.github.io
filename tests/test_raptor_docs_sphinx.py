# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""``extensions = ["raptor_docs.sphinx"]`` builds a minimal project with the skin shipped inside: no network, no external link."""
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from raptor_docs_fixture import SITE_ROOT

CONF = '''project = "Mini"
extensions = ["raptor_docs.sphinx"]
html_theme = "sphinx_book_theme"
html_static_path = ["_static"]
html_css_files = ["mine.css"]
html_theme_options = {"repository_url": "https://github.com/example/mini", "repository_branch": "dev"}
html_baseurl = "https://example.invalid/mini"
'''


class SphinxExtension(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        src = pathlib.Path(cls._tmp.name) / "src"
        (src / "_static").mkdir(parents=True)
        (src / "conf.py").write_text(CONF)
        (src / "_static" / "mine.css").write_text("/* own */")
        (src / "index.rst").write_text("Mini\n====\n\n.. toctree::\n\n   other\n")
        (src / "other.rst").write_text("Other page\n==========\n\ntext\n")
        cls.out = pathlib.Path(cls._tmp.name) / "html"
        cls.build = subprocess.run([sys.executable, "-m", "sphinx", "-b", "html", "-q", "-W", str(src), str(cls.out)],
                                 capture_output=True, text=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(SITE_ROOT), os.environ.get("PYTHONPATH")]))})

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_build_is_warning_free(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)

    def test_the_font_and_the_three_stylesheets_are_in_the_built_static(self):
        for name in ("raptor-tokens.css", "raptor-theme.css", "raptor-reveal.css", "fonts/recursive-full.woff2", "mine.css"):
            self.assertTrue((self.out / "_static" / name).is_file(), name)

    def test_the_stylesheets_load_in_cascade_order(self):
        html = (self.out / "index.html").read_text()
        order = [html.index(n) for n in ("raptor-tokens.css", "raptor-theme.css", "raptor-reveal.css", "mine.css")]
        self.assertEqual(order, sorted(order))

    def test_no_link_or_script_points_outside_the_site(self):
        html = (self.out / "index.html").read_text()
        for tag in re.findall(r"<(?:link|script)\b[^>]*>", html):
            if 'rel="canonical"' in tag:  # the page's own address (html_baseurl), not a fetched resource
                continue
            for url in re.findall(r'(?:href|src)="([^"]+)"', tag):
                self.assertFalse(re.match(r"(?:https?:)?//", url), tag)

    def test_icon_links_and_theme_defaults(self):
        html = (self.out / "index.html").read_text()
        self.assertIn("_static/brand/favicon.svg", html)
        self.assertIn("raptor-family-chip", html)

    def test_llms_txt_lists_the_toctree_in_order(self):
        lines = (self.out / "llms.txt").read_text().splitlines()
        self.assertEqual(lines[0], "# Mini")
        self.assertEqual([ln for ln in lines if ln.startswith("- ")],
                         ["- [Mini](https://example.invalid/mini/index.html)", "- [Other page](https://example.invalid/mini/other.html)"])


if __name__ == "__main__":
    unittest.main()
