# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Landing-site journey fixes, pinned on the committed pages: where each bar's card links, what its caption
records, the axis range, the dense-batch line, the radar's visible axis definitions, the CPU install line, the
Docs chooser, the compatibility table and the start-here notebook's install cell."""
import json
import pathlib
import re
import sys
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_cards

GENERATED = SITE_ROOT / "_generated"
TAG_URL = "https://github.com/amasat01/eagle/blob/v0.6.0/benchmarks/perf_card/"


class CardsAreAuditable(unittest.TestCase):
    def test_every_script_hash_links_to_the_card_file_at_the_release_tag(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        infos = re.findall(r'<div class="rinfo">(.*?)</div>', switch, re.S)
        self.assertGreater(len(infos), 40)
        for info in infos:
            if "script " in info:
                self.assertRegex(info, rf'<a href="{re.escape(TAG_URL)}[^"]+\.json"[^>]*>[0-9.]+ card, script [0-9a-f]{{8}}</a>')

    def test_each_card_caption_records_the_machine_and_the_tools(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        captions = re.findall(r'<p class="axis-note card-env">(.*?)</p>', switch)
        self.assertGreaterEqual(len(captions), 10)                          # six GPUs and four CPUs
        gpu = [c for c in captions if "GPU driver" in c]
        self.assertGreaterEqual(len(gpu), 6)
        for caption in gpu:
            for needle in ("Host CPU", "CUDA runtime", "Warp ", "JAX ", "PyTorch ", "CuPy ", "Card file:"):
                self.assertIn(needle, caption)

    def test_the_environment_line_only_says_what_the_card_records(self):
        card = {"software": {"cpu": "A CPU", "warp": "1.2.3"}, "device": {"driver_version": "999.1", "cuda_runtime": 12090}}
        line = sync_cards.card_environment_line(card)
        self.assertEqual(line, "Host CPU A CPU; GPU driver 999.1; CUDA runtime 12.9; Warp 1.2.3")
        self.assertNotIn("JAX", line)
        self.assertEqual(sync_cards.card_environment_line({}), "")

    def test_the_axis_range_is_explained_not_left_as_a_bare_from(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        self.assertNotIn("Log scale, from", switch)
        self.assertIn("a margin around the fastest and the slowest bar shown", switch)


class HeroAndDense(unittest.TestCase):
    def test_the_dense_batch_is_stated_under_the_hero_from_the_card(self):
        lead = (GENERATED / "lead_sentence.md").read_text()
        self.assertRegex(lead, r'<p class="rpt-lead-dense">When every sample runs the same [\d,]+ steps, '
                               r'eagle\.simulate and NVIDIA Warp tie: [\d.]+ ms against [\d.]+ ms\.</p>')

    def test_the_hero_carries_the_cpu_line_and_the_platform_limit(self):
        index = (SITE_ROOT / "index.md").read_text()
        self.assertIn("pip install raptor-hawk raptor-eagle</code> without an NVIDIA GPU", index)
        self.assertIn("Wheels are Linux x86_64; macOS and Windows", index)

    def test_download_and_colab_point_at_the_same_notebook_path(self):
        for name in ("index.md", "start_here.md"):
            text = (SITE_ROOT / name).read_text()
            self.assertEqual(len(re.findall(r"amasat01\.github\.io/raptor_start_here\.ipynb", text)), 0, name)
            self.assertEqual(len(re.findall(r"main/notebooks/raptor_start_here\.ipynb", text)), 2, name)

    def test_the_docs_nav_is_a_chooser_of_all_four(self):
        index = (SITE_ROOT / "index.md").read_text()
        chooser = re.search(r'<details class="rpt-docs">(.*?)</details>', index, re.S).group(1)
        for repo in ("eagle", "hawk", "raptor", "aether"):
            self.assertIn(f'href="https://amasat01.github.io/{repo}/"', chooser)

    def test_the_cpu_example_is_generated_from_a_run(self):
        text = (GENERATED / "what_you_write_cpu.md").read_text()
        self.assertIn("np.linspace", text)
        self.assertRegex(text, r"```text\nfinished \d+ \[[\d. ]+\]\n```")
        self.assertIn("_generated/what_you_write_cpu.md", (SITE_ROOT / "index.md").read_text())


class Radar(unittest.TestCase):
    def test_every_radar_defines_its_axes_as_visible_text(self):
        for page in ("perf_switch.md", "radar_detailed.md"):
            text = (GENERATED / page).read_text()
            for block in re.split(r'(?=<div class="radar(?: radar-detailed)?" data-side)', text)[1:]:
                visible = re.sub(r"<details.*?</details>", "", block, flags=re.S)
                defs = re.search(r'<dl class="radar-defs"[^>]*>(.*?)</dl>', visible, re.S)
                self.assertIsNotNone(defs, page)
                self.assertGreaterEqual(defs.group(1).count("<dt>"), 6, page)
                self.assertEqual(defs.group(1).count("<dt>"), defs.group(1).count("<dd>"), page)


class StartHere(unittest.TestCase):
    def test_install_section_gives_the_cpu_line_and_the_platform_limit(self):
        text = (SITE_ROOT / "start_here.md").read_text()
        install = text.split("## Install", 1)[1].split("\n## ", 1)[0]
        self.assertIn("pip install raptor-hawk raptor-eagle torch matplotlib", install)
        self.assertIn("Linux x86_64", install)

    def test_the_page_does_not_claim_the_timing_came_from_the_page_builder(self):
        for text in ((SITE_ROOT / "start_here.md").read_text(),
                     (SITE_ROOT / "notebooks" / "raptor_start_here.ipynb").read_text()):
            self.assertNotIn("machine that built this page", text)

    def test_the_notebook_installs_gpu_extras_only_with_a_gpu_and_checks_python(self):
        nb = json.loads((SITE_ROOT / "notebooks" / "raptor_start_here.ipynb").read_text())
        cell = "".join(next(c for c in nb["cells"] if c["cell_type"] == "code")["source"])
        self.assertIn('extra = ""', cell)                       # the GPU extras only with a GPU, matched to its CUDA major
        self.assertIn('extra = f"[cuda{major}]"', cell)
        self.assertLess(cell.index("sys.version_info"), cell.index("google.colab"))
        self.assertNotIn("%pip", cell)

    def test_there_is_no_glossary_box_and_the_limits_are_one_line(self):
        text = (SITE_ROOT / "start_here.md").read_text()
        self.assertNotIn("## Words used below", text)
        self.assertIn("**Limits:**", text)


class Compatibility(unittest.TestCase):
    def test_the_page_separates_shipped_required_and_measured_and_the_install_links_it(self):
        page = (SITE_ROOT / "build_from_source.md").read_text()
        self.assertIn("(compatibility)=", page)
        self.assertIn("| | Shipped | Required | Measured |", page)
        self.assertIn("_generated/compatibility.md", page)
        self.assertIn("{ref}`compatibility table <compatibility>`", (SITE_ROOT / "index.md").read_text())
        self.assertNotIn("tested on NVIDIA GPUs from Pascal to Hopper", (SITE_ROOT / "index.md").read_text())

    def test_the_measured_tables_come_from_the_cards(self):
        text = (GENERATED / "compatibility.md").read_text()
        self.assertRegex(text, r"\| NVIDIA H100 80GB HBM3 \| 9\.0 \| [\d.]+ \| \d+\.\d / \d+\.\d \|")
        self.assertIn("| CPU measured |", text)


if __name__ == "__main__":
    unittest.main()
