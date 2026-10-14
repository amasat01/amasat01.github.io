# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The site shows each measured number once, under one rounding rule.

Self-contained like the rest of the suite (no eagle checkout): it reads the
committed ``_generated/`` pages and the hand-written ones.

- the ratio rule: a ratio is floored to 2 significant figures and spelled one
  way, so 55.7 can never be "55x" in one place and "56x" in another;
- a ratio that two generated pages both show reads identically in both (the
  PyTorch and Warp figures in the hero strip, the glance table and the lead);
- no hand-written page types a wall time or a ratio: every measured figure
  arrives through an ``{include}`` of a generated file.
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_cards

GENERATED = SITE_ROOT / "_generated"
#: Hand-written pages that must carry no measured figure of their own.
HAND_WRITTEN = ("index.md", "start_here.md", "about.md", "compare.md",
                "where_raptor_fits.md", "build_from_source.md", "README.md")
FIGURE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)? ?(?:µs|ms|×|MiB)(?![\w])")
RATIO = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)×")


class RatioRule(unittest.TestCase):
    def test_one_spelling_per_ratio(self):
        f = sync_cards._fmt_ratio
        self.assertEqual({f(55.7), f(55.1), f(55.99)}, {"55×"})
        self.assertEqual(f(53.3), "53×")
        self.assertEqual(f(7.98), "7.9×")
        self.assertEqual(f(3.99), "3.9×")
        self.assertEqual(f(0.995), "0.99×")
        self.assertEqual(sync_cards._fmt_x(55.7), "55×")
        self.assertEqual(f(f_floor := sync_cards._round_sig_floor(41.9)), f(41.9))
        self.assertEqual(f_floor, 41.0)

    def test_generated_ratios_have_at_most_two_significant_figures(self):
        for page in sorted(GENERATED.glob("*.md")):
            for m in RATIO.finditer(page.read_text()):
                value = float(m.group(1))
                self.assertEqual(float(f"{value:.2g}"), value, f"{page.name}: {m.group(0)}")


class SameNumberSameSpelling(unittest.TestCase):
    def test_pytorch_and_warp_ratios_agree_across_pages(self):
        hero = (GENERATED / "hero_strip.md").read_text()
        glance = (GENERATED / "perf_glance.md").read_text()
        for tool in ("PyTorch", "NVIDIA Warp", "JAX", "CuPy"):
            m = re.search(rf"{tool} \((\d+(?:\.\d+)?×)\)", hero)
            if not m:
                continue
            rows = [ln for ln in glance.splitlines() if ln.startswith("|") and tool.split()[-1] in ln]
            ratios = {c.strip() for ln in rows for c in ln.split("|") if c.strip().endswith("×")
                      and not c.strip().startswith("1")}
            self.assertIn(m.group(1), ratios, f"{tool}: hero says {m.group(1)}, tables say {ratios}")


class NoHandTypedFigures(unittest.TestCase):
    def test_hand_written_pages_carry_no_measured_figure(self):
        for name in HAND_WRITTEN:
            text = (SITE_ROOT / name).read_text()
            text = re.sub(r"```\{raw\} html.*?```", " ", text, flags=re.DOTALL)
            left = FIGURE.findall(text)
            self.assertEqual(left, [], f"{name}: measured figures typed by hand: {left}")

    def test_the_compaction_numbers_are_an_include(self):
        text = (SITE_ROOT / "where_raptor_fits.md").read_text()
        self.assertIn("_generated/compaction_numbers.md", text)
        self.assertNotIn("stale-prose-gate", text)


@unittest.skipUnless(os.environ.get("RAPTOR_EAGLE_ROOT"),
                     "RAPTOR_EAGLE_ROOT not set: no eagle checkout to regenerate from")
class RegenerateMatchesCommitted(unittest.TestCase):
    def test_generated_files_are_what_the_cards_give_today(self):
        root = pathlib.Path(os.environ["RAPTOR_EAGLE_ROOT"])
        if not (root / "benchmarks" / "perf_card").is_dir():
            self.skipTest(f"{root} has no benchmarks/perf_card")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sync_cards.main([str(root), "--out-dir", tmp]), 0)
            for fresh in sorted(pathlib.Path(tmp).glob("*.md")):
                self.assertEqual(
                    fresh.read_text(), (GENERATED / fresh.name).read_text(),
                    f"{fresh.name} is stale: re-run tools/sync_cards.py")
            sources = json.loads((pathlib.Path(tmp) / "SOURCES.json").read_text())
            committed = json.loads((GENERATED / "SOURCES.json").read_text())
            self.assertEqual(sources["sources"], committed["sources"])
            self.assertEqual(sources["numbers"], committed["numbers"])


if __name__ == "__main__":
    unittest.main()
