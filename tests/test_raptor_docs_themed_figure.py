# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""A notebook chart is one output of two images (light and dark); the notebook check names a picture that is not."""
import base64
import io
import pathlib
import re
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from raptor_docs import themed_figure
from raptor_docs.nb import check
from test_raptor_docs_capmap import contrast


def figure():
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 1], [0, 1], color="#898781")
    ax.set_title("a title", color="#898781")
    ax.legend(["line"], frameon=True)
    return fig


class ThemedFigure(unittest.TestCase):
    def test_two_images_light_first_dark_hidden(self):
        html = themed_figure.pair_html(figure())
        tags = re.findall(r"<img[^>]*>", html)
        self.assertEqual(len(tags), 2)
        self.assertIn('class="only-light"', tags[0])
        self.assertIn('class="only-dark"', tags[1])
        self.assertIn('style="display:none"', tags[1])
        self.assertNotIn("display:none", tags[0])
        self.assertIn('alt="Chart: a title"', tags[0])

    def test_the_two_images_differ_and_are_transparent(self):
        from PIL import Image
        html = themed_figure.pair_html(figure())
        png = [base64.b64decode(b) for b in re.findall(r"base64,([^\"]*)\"", html)]
        self.assertNotEqual(png[0], png[1])
        im = Image.open(io.BytesIO(png[0]))
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((0, 0))[3], 0)

    def test_text_and_axes_follow_the_mode(self):
        fig = figure()
        for mode, pal in themed_figure.PALETTES.items():
            themed_figure._recolour(fig, pal)
            ax = fig.axes[0]
            self.assertEqual(matplotlib.colors.to_hex(ax.title.get_color()), pal["ink"], mode)
            self.assertEqual(matplotlib.colors.to_hex(ax.spines["left"].get_edgecolor()), pal["sub"], mode)
        plt.close(fig)

    def test_ink_reads_on_each_background(self):
        for pal in themed_figure.PALETTES.values():
            self.assertGreaterEqual(contrast(pal["ink"], pal["bg"]), 4.5)
            self.assertGreaterEqual(contrast(pal["sub"], pal["bg"]), 4.5)

    def test_sync_writes_and_checks_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "themed_figure.py"
            self.assertEqual(themed_figure.sync(copy, check=True), 1)
            self.assertEqual(themed_figure.sync(copy), 0)
            self.assertEqual(themed_figure.sync(copy, check=True), 0)


class NotebookCheck(unittest.TestCase):
    def cell(self, outputs):
        return {"outputs": outputs}

    def test_a_pair_passes_a_bare_image_or_lone_image_is_named(self):
        pair = {"data": {"text/html": '<img class="only-light" src="data:image/png;base64,AA"><img class="only-dark" src="data:image/png;base64,AA">'}}
        lone = {"data": {"text/html": '<img class="only-light" src="data:image/png;base64,AA">'}}
        bare = {"data": {"image/png": "AA"}}
        self.assertEqual(check._unpaired_images(self.cell([pair])), [])
        self.assertEqual(len(check._unpaired_images(self.cell([lone]))), 1)
        self.assertEqual(len(check._unpaired_images(self.cell([bare]))), 1)

    def test_the_budget_counts_images_inside_html(self):
        html = {"data": {"text/html": '<img src="data:image/png;base64,' + "A" * 500 + '">'}}
        self.assertEqual(len(check._oversized_images(self.cell([html]), 100)), 1)
        self.assertEqual(check._oversized_images(self.cell([html]), 10_000), [])


if __name__ == "__main__":
    unittest.main()
