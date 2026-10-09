# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The family cards (_static/ecosystem/) are tools/ecosystem_banner.py's own output.

The generator is the single source of the four package descriptions. This
gate re-runs it in ``--check`` mode: against this site's copies always, and
against a sibling repository's copies (``<repo>/docs/_static/ecosystem/``)
whenever that repository is checked out next to this one; absent siblings
are skipped. It also checks that every page that shows the cards references
files that exist, that the SVGs stay small, well-formed and self-contained, and
that the CSS never transitions a colour (they switch instantly).

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


MODES = ("light", "dark")
SITE = "https://amasat01.github.io"


def _card_refs(focus):
    return [f"ecosystem_card_{p}_{focus}_{m}.svg" for p in PACKAGES for m in MODES]


# page -> the files it must reference (relative to the page's directory)
def _pages():
    pages = {SITE_ROOT / "README.md": [f"_static/ecosystem/{r}" for r in _card_refs("family")],
             SITE_ROOT / "index.md": ["_static/ecosystem/ecosystem_cards_family.html"]}
    for pkg in PACKAGES:
        repo = SITE_ROOT.parent / pkg
        if not repo.is_dir():
            continue
        index = repo / "docs" / ("index.rst" if (repo / "docs" / "index.rst").is_file() else "index.md")
        pages[index] = [f"_static/ecosystem/ecosystem_cards_{pkg}.html"]
        # package READMEs double as the PyPI description, so they use absolute raw URLs
        pages[repo / "README.md"] = [f"{RAW}/{pkg}/main/docs/_static/ecosystem/{r}" for r in _card_refs(pkg)]
    return pages


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


class CardsAreGeneratorOutput(unittest.TestCase):
    def test_check_passes_for_landing_and_present_siblings(self):
        r = _run("--check")
        self.assertEqual(r.returncode, 0, f"card copies are stale:\n{r.stderr}")

    def test_absent_siblings_are_skipped(self):
        with tempfile.TemporaryDirectory() as empty:
            r = _run("--check", "--siblings", empty)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_check_detects_a_stale_svg_and_a_stale_html(self):
        # Non-vacuity: a doctored landing copy must turn --check red.
        for name, old, new in (("ecosystem_card_hawk_family_light.svg", "hawk", "hakw"),
                               ("ecosystem_cards_family.html", "The RAPTOR family", "The RAPTOR famly")):
            target = OUT_DIR / name
            original = target.read_text()
            try:
                target.write_text(original.replace(old, new, 1))
                with tempfile.TemporaryDirectory() as empty:
                    r = _run("--check", "--siblings", empty)
                self.assertNotEqual(r.returncode, 0, f"--check did not notice a changed {name}")
            finally:
                target.write_text(original)


class CardFiles(unittest.TestCase):
    def test_every_card_and_mode_exists(self):
        for ref in _card_refs("family") + ["ecosystem_cards_family.html"]:
            self.assertTrue((OUT_DIR / ref).is_file(), ref)

    def test_no_old_banner_outputs(self):
        self.assertEqual([p.name for p in OUT_DIR.glob("*.svg") if not p.name.startswith("ecosystem_card_")], [])

    def test_svgs_small_wellformed_selfcontained(self):
        for svg in OUT_DIR.glob("*.svg"):
            content = svg.read_text()
            self.assertLess(len(content.encode()), 12_000, f"{svg.name} is over 12 KB")
            xml.dom.minidom.parse(str(svg))
            self.assertIn("<text", content, f"{svg.name}: text must be real SVG text")
            self.assertIn("aria-label", content)
            self.assertNotRegex(content, r"(?:href|src)=\"(?!#)", f"{svg.name} references an external file")
            self.assertNotIn("@import", content)
            self.assertNotIn("@font-face", content)

    def test_here_marker_only_where_a_card_is_the_focus(self):
        for svg in OUT_DIR.glob("*.svg"):
            self.assertNotIn("you are here", svg.read_text(), "the landing (family) cards have no focus card")
        for pkg in PACKAGES:
            d = SITE_ROOT.parent / pkg / "docs" / "_static" / "ecosystem"
            if not d.is_dir():
                continue
            for p in PACKAGES:
                for m in MODES:
                    n = (d / f"ecosystem_card_{p}_{pkg}_{m}.svg").read_text().count("you are here")
                    self.assertEqual(n, 1 if p == pkg else 0, f"{pkg}: card {p}/{m}")

    def test_html_links(self):
        text = (OUT_DIR / "ecosystem_cards_family.html").read_text()
        for pkg in PACKAGES:
            self.assertIn(f'href="{SITE}/{pkg}/"', text)
        self.assertNotIn("you are here", text)

    def test_colours_switch_instantly(self):
        css = re.search(r"<style>(.*?)</style>", (OUT_DIR / "ecosystem_cards_family.html").read_text(), re.S).group(1)
        transitions = re.findall(r"transition:([^;}]*)", css)
        self.assertTrue(transitions, "the hover scale should still animate")
        for t in transitions:
            for prop in re.findall(r"([a-z-]+)\s+[\d.]+s", t):
                self.assertIn(prop, ("transform", "box-shadow"), f"transition on {prop}: {t}")
            self.assertNotRegex(t, r"\b(color|background|border|fill|all)\b", t)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("focus-visible", css)


class PagesReferenceTheCards(unittest.TestCase):
    def test_pages_reference_existing_files(self):
        for page, paths in _pages().items():
            text = page.read_text()
            for ref in paths:
                self.assertIn(ref, text, f"{page} does not reference {ref}")
                rel = ref.split("/main/", 1)[1] if ref.startswith(RAW) else ref
                self.assertTrue((page.parent / rel).is_file(), f"{page}: {rel} missing on disk")

    def test_readme_cards_are_linked_to_their_sites(self):
        for page in (p for p in _pages() if p.name == "README.md"):
            text = page.read_text()
            for pkg in PACKAGES:
                self.assertIn(f'<a href="{SITE}/{pkg}/"><picture>', text, f"{page}: {pkg} card is not a link")
            self.assertIn(f'<a href="{SITE}/"><b>The RAPTOR family</b></a>', text)

    def test_landing_has_no_second_wording_of_the_descriptions(self):
        text = (SITE_ROOT / "index.md").read_text()
        self.assertNotIn("rpt-lib-list", text, "the old four-libraries list is back next to the cards")


if __name__ == "__main__":
    unittest.main()
