# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The family banner (_static/ecosystem/) is tools/ecosystem_banner.py's own output.

The generator is the single source of the four package descriptions. This
gate re-runs it in ``--check`` mode: against this site's copies always, and
against a sibling repository's copies (``<repo>/docs/_static/ecosystem/``)
whenever that repository is checked out next to this one; absent siblings
are skipped. It also checks that every page that shows the banner references
files that exist, and that the SVGs stay small, well-formed and self-contained.

Run with: python -m unittest discover -s tests -v   (see `make check`)
"""
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = SITE_ROOT / "tools" / "ecosystem_banner.py"
OUT_DIR = SITE_ROOT / "_static" / "ecosystem"
PACKAGES = ("aether", "hawk", "eagle", "raptor")
FOCI = ("family",) + PACKAGES

RAW = "https://raw.githubusercontent.com/amasat01"


# page -> the banner paths it must reference (relative to the page's directory)
def _pages():
    family = [f"_static/ecosystem/ecosystem_family_{m}.svg" for m in ("light", "dark")]
    pages = {SITE_ROOT / "index.md": family, SITE_ROOT / "README.md": family}
    for pkg in PACKAGES:
        repo = SITE_ROOT.parent / pkg
        if not repo.is_dir():
            continue
        index = repo / "docs" / ("index.rst" if (repo / "docs" / "index.rst").is_file() else "index.md")
        pages[index] = [f"_static/ecosystem/ecosystem_{pkg}_{m}.svg" for m in ("light", "dark")]
        # package READMEs double as the PyPI description, so they use absolute raw URLs
        pages[repo / "README.md"] = [f"{RAW}/{pkg}/main/docs/_static/ecosystem/ecosystem_{pkg}_{m}.svg"
                                     for m in ("light", "dark")]
    return pages


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


class BannerIsGeneratorOutput(unittest.TestCase):
    def test_check_passes_for_landing_and_present_siblings(self):
        r = _run("--check")
        self.assertEqual(r.returncode, 0, f"banner copies are stale:\n{r.stderr}")

    def test_absent_siblings_are_skipped(self):
        with tempfile.TemporaryDirectory() as empty:
            r = _run("--check", "--siblings", empty)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_check_detects_a_stale_copy(self):
        # Non-vacuity: a doctored landing copy must turn --check red.
        target = OUT_DIR / "ecosystem_family_light.svg"
        original = target.read_text()
        try:
            target.write_text(original.replace("The RAPTOR family", "The RAPTOR famly", 1))
            with tempfile.TemporaryDirectory() as empty:
                r = _run("--check", "--siblings", empty)
            self.assertNotEqual(r.returncode, 0, "--check did not notice a changed copy")
        finally:
            target.write_text(original)


class BannerFiles(unittest.TestCase):
    def test_every_focus_and_mode_exists(self):
        for focus in FOCI:
            for mode in ("light", "dark"):
                self.assertTrue((OUT_DIR / f"ecosystem_{focus}_{mode}.svg").is_file(), f"{focus}/{mode}")

    def test_small_wellformed_selfcontained(self):
        for svg in OUT_DIR.glob("*.svg"):
            content = svg.read_text()
            self.assertLess(len(content.encode()), 30_000, f"{svg.name} is over 30 KB")
            xml.dom.minidom.parse(str(svg))
            self.assertIn("<title", content)
            self.assertIn("<text", content, f"{svg.name}: text must be real SVG text")
            self.assertNotRegex(content, r"(?:href|src)=\"(?!#)", f"{svg.name} references an external file")
            self.assertNotIn("@import", content)
            self.assertNotIn("@font-face", content)

    def test_focus_marker_only_on_package_banners(self):
        for focus in FOCI:
            for mode in ("light", "dark"):
                content = (OUT_DIR / f"ecosystem_{focus}_{mode}.svg").read_text()
                self.assertEqual(content.count("you are here"), 0 if focus == "family" else 1, focus)


class PagesReferenceTheBanner(unittest.TestCase):
    def test_pages_reference_existing_light_and_dark_files(self):
        for page, paths in _pages().items():
            text = page.read_text()
            for ref in paths:
                self.assertIn(ref, text, f"{page} does not reference {ref}")
                rel = ref.split("/main/", 1)[1] if ref.startswith(RAW) else ref
                self.assertTrue((page.parent / rel).is_file(), f"{page}: {rel} missing on disk")

    def test_landing_has_no_second_wording_of_the_descriptions(self):
        text = (SITE_ROOT / "index.md").read_text()
        self.assertNotIn("rpt-lib-list", text, "the old four-libraries list is back next to the banner")


if __name__ == "__main__":
    unittest.main()
