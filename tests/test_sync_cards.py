# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/sync_cards.py and for the committed _generated/ output.

Run with: python -m unittest discover -s tests -v   (see `make check`)

Two kinds of checks live here:

- Unit/integration tests against tests/fixtures/mini_eagle/, a tiny synthetic
  "eagle checkout" committed to this repo. These need no real eagle and run
  in CI.
- A freshness check against the committed _generated/ output itself: every
  number on those pages must trace back to SOURCES.json (catches a hand-edit
  that was never run through sync_cards.py). This also needs no real eagle.
- One optional check that re-hashes the real eagle source files SOURCES.json
  recorded, gated on the RAPTOR_EAGLE_ROOT environment variable; it is
  skipped (not failed) when that is unset, which is the normal case in CI
  (the site's CI must never clone eagle).
"""
import json
import pathlib
import re
import sys
import tempfile
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_cards  # noqa: E402

FIXTURE_EAGLE = SITE_ROOT / "tests" / "fixtures" / "mini_eagle"
GENERATED = SITE_ROOT / "_generated"
NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")


def run_sync(eagle_root, out_dir):
    """Runs sync_cards.main against a private, temporary --out-dir (never the
    real `_generated/`, which a bare run would otherwise overwrite with this
    call's fixture-derived output)."""
    out_dir = pathlib.Path(out_dir)
    rc = sync_cards.main([str(eagle_root), "--out-dir", str(out_dir)])
    assert rc == 0
    return {p.name: (out_dir / p.name).read_text()
            for p in out_dir.iterdir() if p.is_file()}


class CodeBlockParsing(unittest.TestCase):
    def test_basic_roundtrip(self):
        text = (
            "x = 1\n"
            "# >>> code:foo\n"
            "    def f():\n"
            "        return 1\n"
            "# <<< code:foo\n"
            "y = 2\n"
        )
        blocks = sync_cards.code_blocks(text)
        self.assertEqual(set(blocks), {"foo"})
        self.assertIn("def f():", blocks["foo"])
        # dedented: no leading spaces on the common-indent lines
        self.assertTrue(blocks["foo"].splitlines()[0].startswith("def f()"))

    def test_unclosed_block_raises(self):
        text = "# >>> code:foo\nx = 1\n"
        with self.assertRaises(AssertionError):
            sync_cards.code_blocks(text)

    def test_mismatched_marker_raises(self):
        text = "# >>> code:foo\nx = 1\n# <<< code:bar\n"
        with self.assertRaises(AssertionError):
            sync_cards.code_blocks(text)


class ArmSchemaAdapters(unittest.TestCase):
    def test_code_lines_schema(self):
        card = json.loads((FIXTURE_EAGLE / "benchmarks/rk78_card/"
                            "card_fixture-device.json").read_text())
        blocks = sync_cards.arm_blocks_map(card)
        self.assertEqual(blocks["eagle_graph"], ["eagle_body"])
        self.assertEqual(sync_cards.arm_line_count(card, "warp_kernel"), 2)

    def test_code_schema(self):
        card = json.loads((FIXTURE_EAGLE / "benchmarks/perf_card/"
                            "card_fixture-gpu.json").read_text())
        blocks = sync_cards.arm_blocks_map(card)
        self.assertEqual(blocks["cupy_masked"], ["cupy_body"])
        self.assertEqual(sync_cards.arm_line_count(card, "eagle_graph"), 2)

    def test_arm_label_list_schema(self):
        card = json.loads((FIXTURE_EAGLE / "benchmarks/perf_card/"
                            "cpu_card_fixture-host.json").read_text())
        self.assertEqual(sync_cards.arm_keys(card), ["eagle_term8"])
        self.assertEqual(sync_cards.arm_label(card, "eagle_term8"),
                          "eagle host, termination loop, 8 threads")


class GlanceTable(unittest.TestCase):
    def test_ratio_to_fastest_eagle_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))
        glance = out["perf_glance.md"]
        # eagle_graph (1 ms) is the only eagle arm at N=10 -> its own ratio is 1x;
        # cupy_masked (10 ms) is 10x that.
        self.assertIn("1×", glance)
        self.assertIn("10×", glance)
        # the fixture GPU card's device name must be named once per card
        self.assertIn("Fixture GPU", glance)
        self.assertIn("Fixture CPU", glance)
        # memory/compile formatted from the fixture rows
        self.assertIn("2 MiB", glance)
        self.assertIn("500 ms / 50 ms", glance)
        # the CPU card's empty memory/compile rows render as "not available", not a crash
        self.assertIn("–", glance)


class ReferenceDeviceChosenBySlug(unittest.TestCase):
    """``card_fixture-aaa.json`` sorts alphabetically before the fixture's
    reference card (``card_fixture-gpu.json``, ``device_slug`` set to
    ``sync_cards.REFERENCE_SLUGS["perf_gpu"]``). The old ``_first_json``
    picked whichever card sorted first; this proves the reference device is
    still the slug match, and the new, earlier-sorting device shows up only
    in the "Measured on" list."""

    def test_new_earlier_sorting_device_does_not_become_the_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))
        glance = out["perf_glance.md"]
        # the reference device's own table is unaffected by the new card
        self.assertIn("Fixture GPU", glance)
        self.assertIn("1×", glance)
        self.assertIn("10×", glance)
        # the new device appears in "Measured on", linked by its own slug,
        # not chosen as the reference
        self.assertIn("Measured on", glance)
        self.assertIn("Fixture AAA GPU", glance)
        # Hyphenated: Sphinx/docutils normalizes a MyST target label's
        # underscores to hyphens in the built page's HTML id, and this
        # literal external link is never rewritten for it the way an
        # in-build MyST cross-reference would be.
        self.assertIn("#perf-card-gpu-fixture-aaa", glance)
        self.assertIn("#perf-card-gpu-quadro-p2000", glance)

    def test_sources_json_lists_every_card_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))
        sources = json.loads(out["SOURCES.json"])
        paths = {s["path"] for s in sources["sources"]}
        self.assertIn("benchmarks/perf_card/card_fixture-gpu.json", paths)
        self.assertIn("benchmarks/perf_card/card_fixture-aaa.json", paths)

    def test_reference_card_helper_picks_by_slug_not_sort_order(self):
        entries = [("fixture-aaa", {"marker": "aaa"}), ("quadro-p2000", {"marker": "ref"})]
        self.assertEqual(sync_cards.reference_card(entries, "quadro-p2000")["marker"], "ref")
        # no match for the configured slug: falls back to the first by the
        # order it was handed (a single-device tree still works)
        self.assertEqual(sync_cards.reference_card(entries, "no-such-slug")["marker"], "aaa")


class SameTaskFiveWays(unittest.TestCase):
    def test_all_five_tools_present_full_and_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))
        full, short = out["same_task_full.md"], out["same_task_short.md"]
        for tool in ("hawk + eagle", "CuPy", "PyTorch", "JAX", "Warp"):
            self.assertIn(tool, full)
            self.assertIn(tool, short)
        # the full version carries the actual source text of each block
        for needle in ("def eagle_step", "def cupy_step", "def torch_step",
                        "def jax_step", "def warp_step"):
            self.assertIn(needle, full)
        # the short version does not (it is the condensed table only)
        self.assertNotIn("def eagle_step", short)
        # uses the RK7(8) fixture card (present), not the RK4 fallback
        self.assertIn("RK7(8)", full)

    def test_falls_back_to_rk4_card_when_rk78_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            only_perf = tmp / "eagle_root"
            # Same fixture minus the rk78_card directory.
            import shutil
            shutil.copytree(FIXTURE_EAGLE / "benchmarks" / "perf_card",
                             only_perf / "benchmarks" / "perf_card")
            out = run_sync(only_perf, tmp / "out")
        full = out["same_task_full.md"]
        self.assertIn("RK4", full)
        self.assertIn("hawk + eagle", full)
        self.assertIn("CuPy", full)
        self.assertIn("def eagle_step", full)


class Determinism(unittest.TestCase):
    def test_same_input_same_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            out_a = run_sync(FIXTURE_EAGLE, tmp / "a")
            out_b = run_sync(FIXTURE_EAGLE, tmp / "b")
        self.assertEqual(set(out_a), set(out_b))
        for name in out_a:
            if name == "SOURCES.json":
                a = json.loads(out_a[name])
                b = json.loads(out_b[name])
                a.pop("generated_utc")
                b.pop("generated_utc")
                self.assertEqual(a, b)
            else:
                self.assertEqual(out_a[name], out_b[name], name)


class EveryNumberComesFromACard(unittest.TestCase):
    """Mechanical gate on the committed _generated/ output: every numeric
    token on those pages must be present in the SOURCES.json this repo also
    commits, which sync_cards.py writes from the exact same emission path.
    A hand-edit of the generated markdown that was never re-synced will add a
    number this check cannot find, and fail."""

    @classmethod
    def setUpClass(cls):
        if not GENERATED.is_dir():
            raise unittest.SkipTest("_generated/ not built yet -- run tools/sync_cards.py")
        cls.sources = json.loads((GENERATED / "SOURCES.json").read_text())
        cls.pool = set(cls.sources["numbers"])

    def _check(self, name):
        text = (GENERATED / name).read_text()
        found = set(NUM_RE.findall(text))
        missing = found - self.pool
        self.assertFalse(missing, f"{name}: numbers not in SOURCES.json: {sorted(missing)}")

    def test_perf_glance(self):
        self._check("perf_glance.md")

    def test_same_task_full(self):
        self._check("same_task_full.md")

    def test_same_task_short(self):
        self._check("same_task_short.md")

    def test_why_raptor(self):
        self._check("why_raptor.md")

    def test_fastest_arm_grid(self):
        self._check("fastest_arm_grid.md")

    def test_compare(self):
        self._check("compare.md")

    def test_lead_sentence(self):
        self._check("lead_sentence.md")

    def test_compare_time_chart(self):
        # unlike the retired SVG, every number here -- including each bar's
        # log-scale fill-width percentage -- passes through Writer.add(), so
        # even the chart's own layout geometry traces to SOURCES.json.
        self._check("compare_time_chart.md")

    def test_compare_memory_chart(self):
        self._check("compare_memory_chart.md")

    def test_landing_honest(self):
        self._check("landing_honest.md")


class NamedSpeedup(unittest.TestCase):
    """``named_speedup``/``named_speedup_big_text``/``named_speedup_caption``:
    the "name the other guys in the room" comparison that
    replaced "fastest of 14" in hero_strip.md, why_raptor.md and the two
    READMEs. Unit-level, against small synthetic cards -- the fixture-driven
    tests above (HeroStrip, WhyRaptorComparison) check the same thing in
    context."""

    def test_round_sig_floor_never_rounds_up(self):
        # 3.449 would round to 3.4 either way; 9.999 must floor to 9.9, not
        # the 10 that round-half-even would give -- never overstate a margin.
        self.assertEqual(sync_cards._round_sig_floor(3.449), 3.4)
        self.assertEqual(sync_cards._round_sig_floor(9.999), 9.9)
        self.assertEqual(sync_cards._round_sig_floor(41.9), 41.0)
        self.assertIsNone(sync_cards._round_sig_floor(None))
        self.assertIsNone(sync_cards._round_sig_floor(0))

    def test_fmt_ratio_fixed_two_sig_figs(self):
        self.assertEqual(sync_cards._fmt_ratio(3.4), "3.4×")
        self.assertEqual(sync_cards._fmt_ratio(41.0), "41×")

    def _card(self, rows):
        return {"ns": [10], "results": [
            {"n": 10, "arm": arm, "distribution": "spread", "max_steps": 1000,
             "wall_s": {"median": wall}} for arm, wall in rows.items()]}

    def test_named_speedup_order_follows_comparison_arms_not_ratio(self):
        card = self._card({"eagle_simulate": 10.0, "torch_masked": 100.0,
                            "warp_kernel": 20.0})
        n, pairs = sync_cards.named_speedup(card)
        self.assertEqual(n, 10)
        # warp_kernel (2x) listed before torch_masked (10x): COMPARISON_ARMS'
        # own order, never resorted by ratio. jax_vmap/cupy_masked absent
        # from this card are simply skipped.
        self.assertEqual(pairs, [("warp_kernel", 2.0), ("torch_masked", 10.0)])

    def test_big_text_is_the_min_max_floored_range(self):
        pairs = [("warp_kernel", 3.4), ("jax_vmap", 7.4),
                 ("cupy_masked", 41.0), ("torch_masked", 41.0)]
        self.assertEqual(sync_cards.named_speedup_big_text(pairs),
                          "3.4×–41× faster")

    def test_caption_groups_equal_floored_ratios(self):
        # the real card's cupy_masked/torch_masked both floor to 41x and are
        # adjacent in COMPARISON_ARMS -- they must merge into one group.
        pairs = [("warp_kernel", 3.4), ("jax_vmap", 7.4),
                 ("cupy_masked", 41.0), ("torch_masked", 41.0)]
        self.assertEqual(
            sync_cards.named_speedup_caption(pairs),
            "NVIDIA Warp (3.4×), JAX (7.4×), CuPy and PyTorch (41×)")

    def test_caption_does_not_merge_non_adjacent_equal_ratios(self):
        # warp and torch share a ratio but are not adjacent in
        # COMPARISON_ARMS order -- each still gets its own parenthesis.
        pairs = [("warp_kernel", 5.0), ("jax_vmap", 7.0),
                 ("cupy_masked", 9.0), ("torch_masked", 5.0)]
        self.assertEqual(
            sync_cards.named_speedup_caption(pairs),
            "NVIDIA Warp (5.0×), JAX (7.0×), CuPy (9.0×), PyTorch (5.0×)")

    def test_empty_when_base_arm_missing(self):
        card = self._card({"warp_kernel": 20.0})
        n, pairs = sync_cards.named_speedup(card)
        self.assertEqual((n, pairs), (10, []))
        self.assertIsNone(sync_cards.named_speedup_big_text(pairs))
        self.assertEqual(sync_cards.named_speedup_caption(pairs), "")


class MemorySavings(unittest.TestCase):
    """``memory_savings``/``memory_savings_big_text``/``_fmt_mib_int``/
    ``_mem_row``: the "2.6x-3.5x less GPU memory" headline, one level down
    from ``NamedSpeedup`` above (bytes, not wall time). Unit-level, against
    small synthetic cards -- the fixture-driven tests (HeroStrip,
    WhyRaptorComparison, ComparePage) check the same thing in context."""

    def _mem_card(self, rows, n=10, config=None):
        config = config or sync_cards.WHY_CONFIG
        return {"ns": [n], "memory": {"rows": [
            {"arm": arm, "n": n, "distribution": config["distribution"],
             "max_steps": config["max_steps"], "device_peak_bytes": peak_bytes,
             "device_factor": factor}
            for arm, (peak_bytes, factor) in rows.items()
        ]}}

    def test_fmt_mib_int_rounds_to_a_whole_number(self):
        self.assertEqual(sync_cards._fmt_mib_int(4 * 2**20), "4 MiB")
        self.assertEqual(sync_cards._fmt_mib_int(None), "–")

    def test_n_words_spells_out_exactly_a_million(self):
        self.assertEqual(sync_cards._n_words(1_000_000), "a million")
        self.assertEqual(sync_cards._n_words(10), "10")
        self.assertEqual(sync_cards._n_words(1_000), "1,000")

    def test_memory_savings_floors_the_ratio_never_up(self):
        card = self._mem_card({
            "eagle_simulate": (4 * 2**20, 2.0),
            "cupy_masked": (9 * 2**20, 4.5),
            "torch_masked": (11 * 2**20, 5.5),
        })
        n, pairs = sync_cards.memory_savings(card)
        self.assertEqual(n, 10)
        self.assertEqual(pairs, [("cupy_masked", 2.2), ("torch_masked", 2.7)])
        self.assertEqual(sync_cards.memory_savings_big_text(pairs), "2.2×–2.7× less GPU memory")

    def test_memory_savings_single_ratio_has_no_dash(self):
        pairs = [("cupy_masked", 3.0)]
        self.assertEqual(sync_cards.memory_savings_big_text(pairs), "3.0× less GPU memory")

    def test_memory_savings_empty_when_base_arm_missing(self):
        card = self._mem_card({"warp_kernel": (3 * 2**20, 1.5)})
        n, pairs = sync_cards.memory_savings(card)
        self.assertEqual((n, pairs), (10, []))
        self.assertIsNone(sync_cards.memory_savings_big_text(pairs))

    def test_will_it_fit_rows_sorted_lightest_first(self):
        card = self._mem_card({
            "torch_masked": (11 * 2**20, 5.5), "eagle_graph": (2 * 2**20, 1.0),
            "warp_kernel": (3 * 2**20, 1.5),
        })
        rows, n = sync_cards.will_it_fit_rows(card, arms=("torch_masked", "eagle_graph", "warp_kernel"))
        self.assertEqual(n, 10)
        self.assertEqual([arm for arm, _b, _f in rows], ["eagle_graph", "warp_kernel", "torch_masked"])


class HeroStrip(unittest.TestCase):
    """``_generated/hero_strip.md``: the 3 number cards the hero includes
    directly, so none of the three is hand-typed on index.md."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))

    def test_three_grid_item_cards(self):
        text = self.out["hero_strip.md"]
        self.assertEqual(text.count("{grid-item-card}"), 3)
        self.assertIn("5.00 ms", text)
        # the third tile is the memory headline, not "within 1%" (that moved
        # to the honest box -- see test_honest_box_counts_warp_wins_and_the_dense_tie).
        self.assertIn("2.2×–2.7× less GPU memory", text)
        self.assertNotIn("within 1%", text)

    def test_third_card_is_the_memory_headline(self):
        text = self.out["hero_strip.md"]
        # eagle_simulate 4 MiB (2.0x minimum) vs cupy 9 MiB (4.5x) and torch
        # 11 MiB (5.5x) in the fixture's spread/1000, N=10 memory rows.
        self.assertIn("than CuPy and PyTorch — 10 samples in 4 MiB, 2.0× the "
                      "bare minimum state (CuPy 4.5×, PyTorch 5.5×)", text)

    def test_middle_card_names_the_other_tools(self):
        # fixture's spread/1000 cell: eagle_simulate 5 ms vs warp 20 ms (4.0x),
        # jax 40 ms (8.0x), cupy 45 ms (9.0x), torch 50 ms (10x) -- distinct
        # ratios, so no two tools share a parenthesis here (see
        # NamedSpeedup.test_caption_groups_equal_floored_ratios for that).
        text = self.out["hero_strip.md"]
        self.assertIn("4.0×–10× faster", text)
        self.assertIn("than NVIDIA Warp (4.0×), JAX (8.0×), "
                      "CuPy (9.0×), PyTorch (10×)", text)
        self.assertIn("10 samples finishing at different times, up to 1000 steps", text)

    def test_honest_box_counts_warp_wins_and_the_dense_tie(self):
        text = self.out["honest_box.md"]
        # fixture's 3 configs x 1 N = 3 cells; warp_kernel wins "spread,1000"
        # (20 ms vs eagle_simulate's 5 ms? no -- eagle_simulate wins that
        # one; warp only wins "uniform,1000" is a TIE, not an outright win,
        # so the exact count depends on fastest_of_cell's own tie-breaking
        # (lowest wall wins ties too) -- just check the sentence shape.
        self.assertIn("Fixture GPU", text)
        self.assertIn("RK4 cells this card runs", text)

    def test_honest_box_carries_the_within_pct_line_moved_from_the_hero_strip(self):
        text = self.out["honest_box.md"]
        # kernel-only deviation (4 ms vs 4.01 ms) is ~0.25%, ceil'd to 1% --
        # this sentence used to live in hero_strip.md's third tile.
        self.assertIn("`eagle.simulate`'s GPU time is within 1% of the "
                      "hand-tuned version, in every configuration this card runs", text)

    def test_honest_box_memory_line_warp_then_eagle_graph(self):
        text = self.out["honest_box.md"]
        # fixture's spread/1000, N=10 memory rows: warp_kernel 1.5x, eagle_graph
        # (no compaction) 1.0x -- both lighter than eagle_simulate's own 2.0x.
        self.assertIn("NVIDIA Warp is lighter than eagle.simulate (1.5×), and "
                      "hawk + eagle's lower-level building blocks, without compaction, "
                      "are lighter still (1.0×).", text)
        # the whole box stays at or under 3 sentences (a period followed by
        # whitespace/end-of-line; "1.5×"/"1.0×" decimals don't count, since
        # their periods are followed by a digit, not whitespace).
        body = "\n".join(l for l in text.splitlines() if l and not l.startswith("<!--"))
        self.assertLessEqual(len(re.findall(r"\.(?=\s|$)", body, re.M)), 3)


class WhyRaptorComparison(unittest.TestCase):
    """``_generated/why_raptor.md`` + the comparison-chart SVGs: the
    hero-adjacent excerpt, derived from the fixture's spread/1000 and
    uniform/1000 cells (see card_fixture-gpu.json)."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))

    def test_bars_present_fastest_first_with_fixed_decimals(self):
        text = self.out["why_raptor.md"]
        # eagle.simulate (5 ms) is fastest of the fixture's WHY_ARMS cell;
        # torch_masked (50 ms) is slowest -- both must appear, eagle's row
        # ordered before torch's.
        self.assertIn("eagle.simulate", text)
        self.assertIn("5.00 ms", text)
        self.assertIn("50.0 ms", text)
        self.assertLess(text.index("5.00 ms"), text.index("50.0 ms"))

    def test_named_speedup_and_within_pct_are_computed_not_hardcoded(self):
        text = self.out["why_raptor.md"]
        # eagle_simulate (5 ms) vs the fixture's spread/1000 cell: warp 20 ms
        # (4.0x) .. torch 50 ms (10x) -- the sentence names all four, not a
        # bare arm count.
        self.assertIn("`eagle_simulate` is 4.0×–10× faster than "
                      "NVIDIA Warp (4.0×)", text)
        # kernel-only deviation (4 ms vs 4.01 ms) is ~0.25%, ceil'd to 1%.
        self.assertIn("within 1%", text)

    def test_dense_tie_detected_within_3_percent(self):
        text = self.out["why_raptor.md"]
        # fixture's uniform/1000 cell: warp 30 ms vs eagle_graph 30.5 ms
        # (1.67% apart) -- inside the 3% tie band.
        self.assertIn("ties", text)
        self.assertIn("30.0 ms", text)
        self.assertIn("30.5 ms", text)

    def test_rk78_honest_line_and_cpu_beats_every_gpu_arm(self):
        text = self.out["why_raptor.md"]
        # rk78 fixture: eagle_graph 2 ms is the fastest `eagle*` GPU arm;
        # eagle_cpu (0.3 ms) beats warp_kernel (0.5 ms) too, the fixture's
        # true global GPU minimum, so the CPU callout must appear.
        self.assertIn("RK7(8)", text)
        self.assertIn("hawk + eagle on the CPU alone, no GPU at all", text)
        self.assertIn("300 µs", text)

    # The SVG comparison chart was retired in favour of the plain-HTML bar
    # charts of the type-A landing port -- see
    # LandingHeroFragments below for their tests.


class LandingHeroFragments(unittest.TestCase):
    """``_generated/lead_sentence.md``, ``compare_time_chart.md``,
    ``compare_memory_chart.md`` and ``landing_honest.md``: the type-A landing
    hero's own fragments -- plain HTML rows
    (landing.css's track/fill/val), never an SVG, and never a hand-typed
    number. Against the same fixture as HeroStrip/WhyRaptorComparison
    above, so the expected values are the same ones those classes already
    document."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))

    def test_lead_sentence_states_time_memory_and_named_speedup(self):
        # hero_A's own wording, two named ratios: Warp's own ratio (4.0x), and the smaller/never-overstated
        # of CuPy (9.0x) and PyTorch (10x) -- 9.0x.
        text = self.out["lead_sentence.md"]
        self.assertIn("5.00 ms and 4 MiB on a modest workstation GPU", text)
        self.assertIn("4.0× faster than NVIDIA Warp and 9.0× faster than PyTorch or CuPy", text)
        self.assertIn("runs on your CPU", text)
        # never the literal "2017" -- no card field sources that year, so the
        # lead sentence must never hand-type it.
        self.assertNotIn("2017", text)

    def test_time_chart_is_plain_html_rows_fastest_first(self):
        text = self.out["compare_time_chart.md"]
        self.assertIn('class="chart" role="img"', text)
        self.assertIn('class="row us"', text)
        self.assertIn("eagle.simulate", text)
        self.assertIn("5.00 ms", text)
        self.assertIn("50.0 ms", text)
        self.assertLess(text.index("5.00 ms"), text.index("50.0 ms"))
        # no SVG left behind for this chart
        self.assertNotIn("<svg", text)

    def test_memory_chart_lightest_first_same_row_form(self):
        text = self.out["compare_memory_chart.md"]
        self.assertIn('class="chart" role="img"', text)
        self.assertIn("eagle graph", text)
        self.assertIn("1.0×", text)
        self.assertIn("5.5×", text)
        self.assertLess(text.index("1.0×"), text.index("5.5×"))

    def test_landing_honest_names_the_dense_tie_wall_times(self):
        text = self.out["landing_honest.md"]
        self.assertIn('class="honest"', text)
        self.assertIn("fastest arm in 1 of the 3 RK4 cells", text)
        self.assertIn("it ties hawk + eagle (30.0 ms against 30.5 ms)", text)
        self.assertIn("1.0× the minimum against Warp's 1.5×", text)
        self.assertIn("uses 2.0×", text)
        self.assertIn("Fixture GPU", text)


class FastestArmGrid(unittest.TestCase):
    """``_generated/fastest_arm_grid.md``: the compact per-N x configuration
    summary that replaces the 80-row perf_glance table on the landing
    index."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))

    def test_grid_names_the_fastest_arm_per_cell(self):
        text = self.out["fastest_arm_grid.md"]
        # spread/1000, N=10: eagle_simulate (5 ms) beats warp (20 ms).
        self.assertIn("eagle.simulate", text)
        self.assertIn("5.00 ms", text)
        # uniform/1000, N=10: warp (30 ms) beats eagle_graph (30.5 ms).
        self.assertIn("Warp per-thread kernel", text)
        self.assertIn("30.0 ms", text)

    def test_cpu_grid_present_too(self):
        text = self.out["fastest_arm_grid.md"]
        self.assertIn("Fixture CPU", text)
        self.assertIn("eagle host, termination loop, 8 threads", text)


class ComparePage(unittest.TestCase):
    """``_generated/compare.md``: compare.md's per-question body."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))

    def test_every_question_section_present(self):
        text = self.out["compare.md"]
        for heading in ("finish at different times", "batch is dense",
                        "batches are small", "fit on my GPU", "steps are adaptive",
                        "need derivatives", "CPU too"):
            self.assertIn(heading, text)

    def test_links_to_eagles_performance_page_anchors(self):
        text = self.out["compare.md"]
        # Hyphenated to match the built page's docutils-normalized id, not
        # the underscored MyST target label itself (see
        # build_measured_on's comment in sync_cards.py).
        self.assertIn("#perf-card-gpu-quadro-p2000", text)
        self.assertIn("#rk78-card-gpu-fixture-device", text)

    def test_will_it_fit_table_lightest_first_with_minimum_ratio(self):
        text = self.out["compare.md"]
        self.assertIn("## Will it fit on my GPU?", text)
        self.assertIn("| tool | GPU memory | × minimum |", text)
        # fixture's spread/1000, N=10 memory rows, lightest first: eagle
        # graph (no compaction) 2 MiB/1x, eagle.simulate 4 MiB/2x, Warp
        # 3 MiB/1.5x, JAX 6 MiB/3x, CuPy 9 MiB/4.5x, PyTorch 11 MiB/5.5x.
        self.assertIn("| hawk + eagle graph (no compaction) | 2 MiB | 1×", text)
        self.assertIn("| eagle.simulate | 4 MiB | 2×", text)
        self.assertIn("| NVIDIA Warp | 3 MiB | 1.5×", text)
        self.assertIn("| PyTorch | 11 MiB | 5.5×", text)
        # within the table itself (not the rest of the page, which mentions
        # "eagle.simulate" earlier via the "finish at different times"
        # section) -- lightest row first.
        self.assertLess(text.index("| hawk + eagle graph (no compaction) | 2 MiB"),
                         text.index("| NVIDIA Warp | 3 MiB"))
        self.assertLess(text.index("| NVIDIA Warp | 3 MiB"),
                         text.index("| eagle.simulate | 4 MiB"))
        # the friendly sentence states Warp's lighter figure plainly, and
        # names hawk + eagle's own lower-level, uncompacted arm too.
        self.assertIn("NVIDIA Warp is lighter than eagle.simulate (1.5×), and "
                      "hawk + eagle's lower-level building blocks, without compaction, "
                      "are lighter still (1.0×).", text)


class WarpClaimsFollowTheCard(unittest.TestCase):
    """The comparative Warp sentences (Warp's RK4 cell wins; which of Warp and
    eagle.simulate is lighter; "lighter still") are computed from the card,
    never fixed prose: each branch is driven by a mutated copy of the fixture
    GPU card."""

    CARD = "benchmarks/perf_card/card_fixture-gpu.json"

    def _run(self, mutate):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "eagle"
            shutil.copytree(FIXTURE_EAGLE, root)
            path = root / self.CARD
            card = json.loads(path.read_text())
            mutate(card)
            path.write_text(json.dumps(card))
            return run_sync(root, pathlib.Path(tmp) / "out")

    @staticmethod
    def _factors(sim, warp, graph):
        def mutate(card):
            want = {"eagle_simulate": sim, "warp_kernel": warp, "eagle_graph": graph}
            for r in card["memory"]["rows"]:
                if r["arm"] in want:
                    r["device_factor"] = want[r["arm"]]
        return mutate

    @staticmethod
    def _warp_never_wins(card):
        for r in card["results"]:
            if r["arm"] == "warp_kernel":
                for k in r["wall_s"]:
                    r["wall_s"][k] *= 1000

    def test_rule1_warp_wins_some_cells(self):
        out = self._run(lambda c: None)
        for name, needle in (
                ("landing_honest.md", "NVIDIA Warp is an excellent per-thread kernel compiler: "
                                      "it is the fastest arm in 1 of the 3 RK4 cells this card runs, "
                                      "and when every sample runs all 1000 steps"),
                ("why_raptor.md", "- **Warp is excellent at per-thread kernels**: it is the "
                                  "fastest arm in 1 of 3 cells, and ")):
            self.assertIn(needle, out[name])
        for text in out.values():
            self.assertNotIn("wins small", text)

    def test_rule1_warp_wins_no_cells(self):
        out = self._run(self._warp_never_wins)
        self.assertIn("NVIDIA Warp is an excellent per-thread kernel compiler: "
                      "when every sample runs all 1000 steps hawk + eagle beats it",
                      out["landing_honest.md"])
        self.assertIn("- **Warp is excellent at per-thread kernels**: it trails hawk + eagle "
                      "here on a fully dense batch", out["why_raptor.md"])
        self.assertNotIn("fastest arm in 0", out["landing_honest.md"])
        self.assertNotIn("fastest arm in 0", out["why_raptor.md"])

    def test_rule2_warp_lighter_keeps_the_sentence(self):
        out = self._run(self._factors(2.0, 1.5, 1.0))
        want = ("NVIDIA Warp is lighter than eagle.simulate (1.5×), and hawk + eagle's "
                "lower-level building blocks, without compaction, are lighter still (1.0×).")
        self.assertIn(want, out["honest_box.md"])
        self.assertIn(want, out["compare.md"])

    def test_rule2_eagle_simulate_lighter(self):
        out = self._run(self._factors(1.2, 1.5, 1.0))
        want = ("eagle.simulate (1.2×) is lighter than NVIDIA Warp (1.5×), and hawk + eagle's "
                "lower-level building blocks, without compaction, are lighter still (1.0×).")
        self.assertIn(want, out["honest_box.md"])
        self.assertIn(want, out["compare.md"])
        self.assertNotIn("Warp is lighter", out["honest_box.md"])

    def test_rule2_lighter_still_only_when_graph_is_below_both(self):
        out = self._run(self._factors(1.2, 1.5, 1.4))
        want = "eagle.simulate (1.2×) is lighter than NVIDIA Warp (1.5×)."
        self.assertIn(want, out["honest_box.md"])
        self.assertIn(want, out["compare.md"])
        self.assertNotIn("lighter still", out["honest_box.md"])
        self.assertNotIn("lighter still", out["compare.md"])

    def test_landing_memory_paragraph_follows_the_card(self):
        out = self._run(self._factors(1.6, 1.7, 1.3))
        self.assertIn("building blocks go lighter than Warp: 1.3×", out["landing_honest.md"])
        out = self._run(self._factors(1.6, 1.2, 1.3))
        self.assertIn("building blocks and Warp compare: 1.3×", out["landing_honest.md"])
        self.assertNotIn("go lighter than Warp", out["landing_honest.md"])

class SourcesFreshnessIfEagleAvailable(unittest.TestCase):
    """Optional: re-run sync is a no-op. Only runs if RAPTOR_EAGLE_ROOT points
    at a real eagle checkout holding the files SOURCES.json recorded; this is
    never true in CI (CI must not clone eagle), so it skips there."""

    def test_recorded_md5s_still_match(self):
        import os
        root = os.environ.get("RAPTOR_EAGLE_ROOT")
        if not root or not GENERATED.is_dir():
            raise unittest.SkipTest("RAPTOR_EAGLE_ROOT not set; skipped in CI by design")
        root = pathlib.Path(root)
        sources = json.loads((GENERATED / "SOURCES.json").read_text())
        for entry in sources["sources"]:
            p = root / entry["path"]
            if not p.is_file():
                continue
            self.assertEqual(sync_cards._md5(p), entry["md5"], entry["path"])


if __name__ == "__main__":
    unittest.main()
