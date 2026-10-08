# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Tests for the hand-authored explanatory SVGs under _static/figures/.

Every figure is referenced from the MyST source as a light/dark pair of
{image} directives (swapped by the theme's .only-light / .only-dark classes).
This file is a mechanical gate, not a renderer: it parses those directives
out of the pages that reference them and checks that every referenced file
exists on disk, that both the light and the dark file exist for every
figure, and that every reference carries non-empty alt text. It also does a
couple of cheap sanity checks directly on the SVG files themselves (real
<text> elements, no sub-12px font sizes) so a future hand-edit can't quietly
drop the accessibility properties the brief asked for.

Run with: python -m unittest discover -s tests -v   (see `make check`)
"""
import pathlib
import re
import unittest
import xml.dom.minidom

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIGURES_DIR = SITE_ROOT / "_static" / "figures"

# Pages that are allowed to reference figures (figures 1
# and 3 on where_raptor_fits.md, figure 1 small on index.md, figure 2 next to
# the finished-samples explanation -- also on where_raptor_fits.md; the
# what_you_write Warp/RAPTOR comparison sits next to "Same task, five ways",
# also on where_raptor_fits.md).
PAGES = ["index.md", "where_raptor_fits.md"]

# One {image} directive, MyST/docutils colon-fence form:
# ```{image} <path>
# :alt: ...
# :class: ...
# ```
IMAGE_BLOCK_RE = re.compile(
    r"```\{image\}\s*(?P<path>\S+)\n(?P<options>(?::[a-zA-Z-]+:.*\n)*)```",
    re.MULTILINE,
)
OPTION_RE = re.compile(r":([a-zA-Z-]+):\s*(.*)")


def parse_image_directives(text):
    """Return a list of dicts: {path, alt, class} for every {image} block."""
    out = []
    for m in IMAGE_BLOCK_RE.finditer(text):
        path = m.group("path").strip()
        opts = {}
        for line in m.group("options").splitlines():
            om = OPTION_RE.match(line.strip())
            if om:
                opts[om.group(1)] = om.group(2).strip()
        out.append({
            "path": path,
            "alt": opts.get("alt", ""),
            "class": opts.get("class", ""),
        })
    return out


def all_directives():
    found = []
    for name in PAGES:
        text = (SITE_ROOT / name).read_text()
        for d in parse_image_directives(text):
            d["page"] = name
            found.append(d)
    return found


class FigureReferencesResolve(unittest.TestCase):
    """Every {image} directive on a landing page must point at a file that
    actually exists under the repo root."""

    def test_at_least_the_three_figures_are_referenced(self):
        directives = all_directives()
        self.assertTrue(directives, "no {image} directives found on the landing pages")
        stems = {pathlib.Path(d["path"]).name for d in directives}
        for expected in (
            "where_raptor_fits_light.svg", "where_raptor_fits_dark.svg",
            "stack_light.svg", "stack_dark.svg",
            "finished_samples_light.svg", "finished_samples_dark.svg",
            "what_you_write_light.svg", "what_you_write_dark.svg",
        ):
            self.assertIn(expected, stems, f"{expected} is never referenced from {PAGES}")

    def test_every_referenced_path_exists_on_disk(self):
        for d in all_directives():
            p = SITE_ROOT / d["path"]
            self.assertTrue(p.is_file(), f"{d['page']}: {d['path']} does not exist")


class FigureHasBothModes(unittest.TestCase):
    """Every figure referenced in light mode must also be referenced in dark
    mode (and vice versa) -- a mode swapped via .only-light/.only-dark must
    never be the only one shipped, and both files must be present on disk
    regardless of whether a page happens to reference them."""

    def test_light_and_dark_both_referenced(self):
        directives = all_directives()
        by_class = {"only-light": set(), "only-dark": set()}
        for d in directives:
            self.assertIn(d["class"], by_class,
                           f"{d['page']}: {d['path']} has no only-light/only-dark class")
            stem = re.sub(r"_(light|dark)\.svg$", "", pathlib.Path(d["path"]).name)
            by_class[d["class"]].add(stem)
        self.assertEqual(by_class["only-light"], by_class["only-dark"],
                          "a figure is referenced in one mode but not the other")

    def test_every_figures_dir_svg_has_a_sibling_in_the_other_mode(self):
        svgs = {p.name for p in FIGURES_DIR.glob("*.svg")}
        self.assertTrue(svgs, "_static/figures/ has no SVGs")
        for name in svgs:
            if name.endswith("_light.svg"):
                sibling = name[: -len("_light.svg")] + "_dark.svg"
            elif name.endswith("_dark.svg"):
                sibling = name[: -len("_dark.svg")] + "_light.svg"
            else:
                self.fail(f"{name} is neither a *_light.svg nor a *_dark.svg")
            self.assertIn(sibling, svgs, f"{name} has no {sibling} counterpart")


class FigureReferencesHaveAltText(unittest.TestCase):
    def test_every_image_directive_has_nonempty_alt(self):
        for d in all_directives():
            self.assertTrue(d["alt"], f"{d['page']}: {d['path']} has no :alt: text")
            self.assertGreater(len(d["alt"]), 10,
                                f"{d['page']}: {d['path']} alt text looks too short to be descriptive")


class FigureSVGSanity(unittest.TestCase):
    """Cheap, direct checks on the SVG files: real SVG text (not paths
    pretending to be text), and no font below the 12px floor the brief set."""

    FONT_SIZE_RE = re.compile(r'font-size="([0-9.]+)(px)?"')

    def test_every_svg_has_real_text_elements(self):
        svgs = list(FIGURES_DIR.glob("*.svg"))
        self.assertTrue(svgs)
        for svg in svgs:
            content = svg.read_text()
            self.assertIn("<text", content, f"{svg.name} has no <text> elements")

    def test_no_font_size_below_12px(self):
        for svg in FIGURES_DIR.glob("*.svg"):
            content = svg.read_text()
            for value, _unit in self.FONT_SIZE_RE.findall(content):
                self.assertGreaterEqual(
                    float(value), 12.0,
                    f"{svg.name} has font-size {value}, below the 12px floor")

    def test_every_svg_is_well_formed_xml(self):
        # An SVG embedded through <img src="...svg"> is parsed as strict XML
        # by the browser (unlike some standalone SVG renderers, which are
        # more forgiving): a stray "--" inside an XML comment, for example,
        # makes the whole document fail to parse and the image never shows
        # up at all. This caught exactly that bug once already.
        for svg in FIGURES_DIR.glob("*.svg"):
            try:
                xml.dom.minidom.parse(str(svg))
            except Exception as exc:  # noqa: BLE001 -- report any parse failure
                self.fail(f"{svg.name} is not well-formed XML: {exc}")

    def test_every_svg_has_title_and_viewbox(self):
        for svg in FIGURES_DIR.glob("*.svg"):
            content = svg.read_text()
            self.assertIn("viewBox=", content, f"{svg.name} has no viewBox (won't scale cleanly)")
            self.assertIn("<title", content, f"{svg.name} has no <title> for a standalone open")


if __name__ == "__main__":
    unittest.main()
