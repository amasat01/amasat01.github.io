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
  skipped (not failed) when that is unset, which is the normal case on a
  site-only checkout.
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


class DenseClauseOrder(unittest.TestCase):
    """The subject's number comes first and each number is attributed."""

    def _clause(self, verdict):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sync_cards.Pool(pathlib.Path(tmp))
            return sync_cards.dense_clause(pool, {"verdict": verdict, "warp_s": 0.220, "eagle_s": 0.211})

    def test_eagle_wins(self):
        self.assertEqual(self._clause("eagle"), "hawk + eagle beats it: 211 ms against Warp's 220 ms")

    def test_tie(self):
        self.assertEqual(self._clause("tie"), "it ties hawk + eagle: 220 ms against hawk + eagle's 211 ms")

    def test_warp_wins(self):
        self.assertEqual(self._clause("warp"), "it beats hawk + eagle: 220 ms against hawk + eagle's 211 ms")


class DefaultDeviceChosenByPreference(unittest.TestCase):
    """The text quotes the DEFAULT card: the first in the tab preference
    list, else the first alphabetically -- never a hard-coded device."""


    def test_sources_json_lists_every_card_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))
        sources = json.loads(out["SOURCES.json"])
        paths = {s["path"] for s in sources["sources"]}
        self.assertIn("benchmarks/perf_card/card_fixture-gpu.json", paths)
        self.assertIn("benchmarks/perf_card/card_fixture-aaa.json", paths)

    def test_default_card_helper_follows_the_preference_list(self):
        entries = [("a", {"device": {"name": "Quadro P2000"}, "ns": [1]}), ("b", {"device": {"name": "Tesla T4"}, "ns": [1]})]
        self.assertEqual(sync_cards.default_card(entries, sync_cards.GPU_PREFERENCE)["device"]["name"], "Tesla T4")
        self.assertIsNone(sync_cards.default_card([], sync_cards.GPU_PREFERENCE))


def _cpu_card(model="Synthetic CPU", slug="synthetic-cpu", date="2026-01-02T03:04:05Z",
              eagle_wall=0.1, other_wall=0.5, loop_n=1000):
    """A minimal perf_cpu card: eagle (8 threads) and a plain-loop arm that
    only ran at a smaller N, spread/uniform S=1000 at two batch sizes."""
    results = []
    for dist in ("spread", "uniform"):
        for n in (1000, 1_000_000):
            results.append({"arm": "eagle_cpu8", "n": n, "distribution": dist,
                            "max_steps": 1000, "wall_s": {"median": eagle_wall}})
            results.append({"arm": "numba_prange", "n": n, "distribution": dist,
                            "max_steps": 1000, "wall_s": {"median": other_wall}})
        results.append({"arm": "python_loops", "n": loop_n, "distribution": dist,
                        "max_steps": 1000, "wall_s": {"median": 2.0}})
        results.append({"arm": "eagle_cpu8", "n": 1000, "distribution": dist,
                        "max_steps": 100, "wall_s": {"median": 9.0}})
    return {
        "cpu_slug": slug, "generated_utc": date,
        "cpu": {"model": model, "cores": 4, "logical_cpus": 8},
        "workload": {"problem": "synthetic oscillator"},
        "ns": [1000, 1_000_000],
        "arms": ["eagle_cpu8", "numba_prange", "python_loops", "eagle_compact8"],
        "arm_labels": {"eagle_cpu8": "eagle label", "numba_prange": "numba label",
                       "python_loops": "loops label", "eagle_compact8": "compact label"},
        "results": results,
        "fit": {"intro": "Intro sentence about loops.",
                "arms": {"eagle_cpu8": "Eagle fits here. On this card: spread S=1000: 100 ms.",
                         "numba_prange": "Numba fits here. On this card: 3.46x.",
                         "python_loops": "Loops fit here.",
                         "eagle_compact8": "Compaction fits here."}},
    }


def _render_cpu(entries):
    with tempfile.TemporaryDirectory() as tmp:
        pool = sync_cards.Pool(pathlib.Path(tmp))
        return sync_cards.build_perf_switch(pool, [], entries)


class CpuGlance(unittest.TestCase):
    """``_generated/cpu_glance.md``: one block per CPU card of the family."""

    def test_values_match_the_card(self):
        text, ok = _render_cpu([("synthetic-cpu", _cpu_card())])
        self.assertTrue(ok)
        self.assertIn("100 ms", text)           # eagle wall at the largest N, spread S=1000
        self.assertIn("500 ms", text)           # numba wall
        self.assertIn("Synthetic CPU", text)
        self.assertIn("4 cores, 8 logical CPUs", text)
        self.assertIn("card of 2026-01-02", text)
        self.assertIn("#perf-card-cpu-synthetic-cpu", text)
        self.assertTrue(text.startswith("<!-- Generated by tools/sync_cards.py; do not edit. -->"))

    def test_bars_use_the_gpu_chart_markup_and_tool_colours(self):
        text, _ = _render_cpu([("synthetic-cpu", _cpu_card())])
        self.assertIn('<div class="chart"', text)
        self.assertIn('class="row us"', text)              # eagle's bar
        self.assertIn("var(--tool-raptor)", text)
        self.assertIn("var(--tool-numba)", text)
        self.assertIn("Log scale", text)

    def test_only_the_charted_tools_and_config(self):
        text, _ = _render_cpu([("synthetic-cpu", _cpu_card())])
        self.assertNotIn("compact label", text)       # compaction arms live on the full card
        self.assertNotIn("loops label", text)         # plain loops did not run at the top N
        self.assertNotIn("9 s", text)                 # S=100 cell is not charted
        self.assertNotIn("2 s", text)                 # uniform cell is not charted

    def test_the_bars_name_tools_not_card_labels(self):
        text, _ = _render_cpu([("synthetic-cpu", _cpu_card())])
        self.assertIn("eagle, 8 threads", text)
        self.assertIn(">Numba<", text)
        self.assertNotIn("</span>numba label</div>", text)   # a bar names the tool (the info line may quote the card)

    def test_tab_label_drops_trademarks_and_clock(self):
        card = _cpu_card(model="Intel(R) Xeon(R) W-2125 CPU @ 4.00GHz")
        self.assertEqual(sync_cards.cpu_tab_label(card), "Intel Xeon W-2125")

    def test_css_defines_the_new_tool_colours(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        for var in ("--tool-numba:", "--tool-numpy:"):
            self.assertIn(var, css)

    def test_every_cpu_card_is_rendered_one_tab_each(self):
        entries = [("synthetic-cpu", _cpu_card()),
                   ("arm-box", _cpu_card(model="Other ARM CPU", slug="arm-box",
                                          date="2026-02-03T00:00:00Z", other_wall=0.2))]
        text, _ = _render_cpu(entries)
        self.assertEqual(text.count("<label for=\"perf-cpu-"), 2)
        self.assertIn("Other ARM CPU", text)
        self.assertIn("#perf-card-cpu-arm-box", text)
        self.assertIn("card of 2026-02-03", text)

    def test_one_card_still_uses_the_tab_markup(self):
        text, _ = _render_cpu([("synthetic-cpu", _cpu_card())])
        self.assertIn('class="perf-chips"', text)
        self.assertEqual(text.count('<label for="perf-cpu-'), 1)

    def test_default_tab_follows_the_preference_list(self):
        entries = [("a", _cpu_card(model="Intel(R) Xeon(R) W-2125 CPU @ 4.00GHz", slug="a")),
                   ("b", _cpu_card(model="Intel(R) Xeon(R) Platinum 8480+", slug="b")),
                   ("c", _cpu_card(model="Acme Z9", slug="c"))]
        text, _ = _render_cpu(entries)
        order = [text.index(f">{n}</label>") for n in
                 ("Intel Xeon Platinum 8480+", "Intel Xeon W-2125", "Acme Z9")]
        self.assertEqual(order, sorted(order))

    def test_gpu_preference_and_unknown_devices(self):
        entries = [("x", {"device": {"name": "Zed GPU"}}), ("p", {"device": {"name": "Quadro P2000"}}),
                   ("t", {"device": {"name": "Tesla T4"}}), ("h", {"device": {"name": "NVIDIA H100 80GB"}}),
                   ("a", {"device": {"name": "Alpha GPU"}})]
        got = [slug for slug, _ in sync_cards.in_tab_order(entries, sync_cards.GPU_PREFERENCE)]
        self.assertEqual(got, ["h", "t", "p", "a", "x"])

    def test_no_card_renders_a_note_not_a_crash(self):
        text, ok = _render_cpu([])
        self.assertFalse(ok)
        self.assertNotIn("tab-set", text)

    def test_index_puts_the_comparison_right_after_the_hero(self):
        index = (SITE_ROOT / "index.md").read_text()
        order = [index.index(h) for h in
                 ("(how-it-compares)=", "## What you write", "## Four libraries")]
        self.assertEqual(order, sorted(order))
        self.assertLess(index.index("rpt-thread"), index.index("(how-it-compares)="))
        self.assertIn("_generated/perf_switch.md", index)
        self.assertNotIn("## On your CPU", index)       # merged into the switch
        self.assertIn("perf-gpu-only", index)


def _render_switch(gpus, cpus):
    with tempfile.TemporaryDirectory() as tmp:
        pool = sync_cards.Pool(pathlib.Path(tmp))
        return sync_cards.build_perf_switch(pool, gpus, cpus)


class PerfSwitch(unittest.TestCase):
    """``_generated/perf_switch.md``: On a GPU | On a CPU, device chips under it."""

    def setUp(self):
        self.cpu = [("c1", _cpu_card()), ("c2", _cpu_card(model="Intel(R) Xeon(R) Platinum 8480+", slug="c2"))]
        self.gpu = [("g1", _cpu_card(model="Quadro P2000", slug="g1"))]

    def test_two_levels_of_radios_with_a_default(self):
        text, ok = _render_switch([], self.cpu)
        self.assertTrue(ok)
        self.assertIn('role="radiogroup" aria-label="Hardware"', text)
        self.assertEqual(text.count('name="perf-hw"'), 1)      # one side present: no GPU side
        self.assertEqual(text.count('name="perf-cpu"'), 2)     # one chip per CPU
        self.assertEqual(text.count(" checked>"), 2)           # defaults: the side and the first chip

    def test_default_chip_is_first_in_the_preference_list(self):
        text, _ = _render_switch([], self.cpu)
        self.assertLess(text.index("Intel Xeon Platinum 8480+"), text.index("Synthetic CPU"))

    def test_cpu_side_says_memory_is_gpu_only(self):
        text, _ = _render_switch([], self.cpu)
        self.assertIn(sync_cards.GPU_ONLY_NOTE, text)

    def test_old_anchor_is_kept_and_selects_the_cpu_side(self):
        text, _ = _render_switch([], self.cpu)
        self.assertIn('id="on-your-cpu"', text)
        self.assertIn('#on-your-cpu', text)

    def test_nothing_to_show_renders_nothing(self):
        text, ok = _render_switch([], [])
        self.assertFalse(ok)
        self.assertNotIn("perf-switch", text)

    def test_css_has_the_two_levels(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        for sel in (".perf-seg", ".perf-chips", "#perf-hw-cpu:checked ~ .perf-side-cpu",
                    ":focus-visible"):
            self.assertIn(sel, css)

    def test_the_fixture_cpu_card_gets_its_tab(self):
        # the fixture card is in eagle's current CPU-card format: an arm-name change in the card must not
        # drop the CPU side silently
        with tempfile.TemporaryDirectory() as d:
            run_sync(FIXTURE_EAGLE, pathlib.Path(d))
            text = (pathlib.Path(d) / "perf_switch.md").read_text()
        self.assertIn('id="perf-hw-cpu"', text)
        self.assertIn('data-slug="fixture-host"', text)

    def test_every_cpu_card_the_site_cites_has_a_tab(self):
        sources = json.loads((GENERATED / "SOURCES.json").read_text())
        cited = sorted(re.match(r"benchmarks/perf_card/cpu_card_(.+)\.json$", e["path"]).group(1)
                       for e in sources["sources"] if re.match(r"benchmarks/perf_card/cpu_card_.+\.json$", e["path"]))
        text = (GENERATED / "perf_switch.md").read_text()
        tabs = sorted(re.findall(r'name="perf-cpu" id="perf-cpu-\d+" data-slug="([^"]+)"', text))
        self.assertEqual(tabs, cited)


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

    def test_compare_memory_chart(self):
        self._check("compare_memory_chart.md")


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


    def test_memory_savings_single_ratio_has_no_dash(self):
        pairs = [("cupy_masked", 3.0)]
        self.assertEqual(sync_cards.memory_savings_big_text(pairs), "3.0× less GPU memory")




class HeroStrip(unittest.TestCase):
    """``_generated/hero_strip.md``: the 3 number cards the hero includes
    directly, so none of the three is hand-typed on index.md."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))








class WhyRaptorComparison(unittest.TestCase):
    """``_generated/why_raptor.md`` + the comparison-chart SVGs: the
    hero-adjacent excerpt, derived from the fixture's spread/1000 and
    uniform/1000 cells (see card_fixture-gpu.json)."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))





    # The SVG comparison chart was retired in favour of the plain-HTML bar
    # charts of the type-A landing port -- see
    # LandingHeroFragments below for their tests.


class LandingHeroFragments(unittest.TestCase):
    """``_generated/lead_sentence.md``, ``perf_switch.md``,
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






class FastestArmGrid(unittest.TestCase):
    """``_generated/fastest_arm_grid.md``: the compact per-N x configuration
    summary that replaces the 80-row perf_glance table on the landing
    index."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))




class ComparePage(unittest.TestCase):
    """``_generated/compare.md``: compare.md's per-question body."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.out = run_sync(FIXTURE_EAGLE, pathlib.Path(tmp))





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


class DeviceReadingValidity(unittest.TestCase):
    """A device reading below the workload's minimum state (less one driver
    page) is withheld, never published: the run cannot have fit in less."""

    def test_reading_below_minimum_is_withheld(self):
        mib = 2**20
        self.assertFalse(sync_cards.device_reading_valid(
            {"device_peak_bytes": 0, "minimum_bytes": 40 * mib}))
        self.assertTrue(sync_cards.device_reading_valid(
            {"device_peak_bytes": 50 * mib, "minimum_bytes": 40 * mib}))
        # small N: the driver's ~2 MiB page granularity can read 0 honestly
        self.assertTrue(sync_cards.device_reading_valid(
            {"device_peak_bytes": 0, "minimum_bytes": 40_000}))
        self.assertTrue(sync_cards.device_reading_valid(
            {"device_peak_bytes": None, "minimum_bytes": 40 * mib}))

    def test_committed_output_quotes_no_impossible_reading(self):
        text = (GENERATED / "compare.md").read_text()
        self.assertNotRegex(text, r"\| 0 MiB \| 0× \|")

    def test_withheld_reading_borrows_the_family_value(self):
        mib = 2**20
        def card(peak, name):
            return {"device": {"name": name}, "memory": {"rows": [
                {"arm": "jax_vmap", "n": 10**6, "device_peak_bytes": peak, "minimum_bytes": 40 * mib}]}}
        l4, p2, t4 = card(None, "L4"), card(128 * mib, "P2000"), card(128 * mib, "T4")
        l4["memory"]["rows"][0]["device_withheld"] = True
        sync_cards.borrow_withheld_readings([("l4", l4), ("p2", p2), ("t4", t4)])
        row = l4["memory"]["rows"][0]
        self.assertEqual(row["device_peak_bytes"], 128 * mib)
        self.assertEqual(row["device_borrowed_from"], ["P2000", "T4"])
        # disagreeing cards: stays withheld
        l4b = card(None, "L4"); l4b["memory"]["rows"][0]["device_withheld"] = True
        sync_cards.borrow_withheld_readings([("l4", l4b), ("p2", card(128 * mib, "P2000")),
                                             ("x", card(256 * mib, "X"))])
        self.assertIsNone(l4b["memory"]["rows"][0]["device_peak_bytes"])


class CpuMemoryNetOfHarnessCopies(unittest.TestCase):
    """CPU peak memory is published net of the harness's copies (36 bytes per
    sample on the RK4 CPU card's eagle arms); the rule mirrors eagle's."""




    def test_matches_eagles_function_on_every_cpu_card(self):
        import importlib.util
        import os
        root = os.environ.get("RAPTOR_EAGLE_ROOT")
        common = pathlib.Path(root or "/nonexistent") / "benchmarks" / "_card_common.py"
        if not common.is_file():
            self.skipTest("no eagle root (RAPTOR_EAGLE_ROOT)")
        spec = importlib.util.spec_from_file_location("eagle_card_common", common)
        cc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cc)
        checked = 0
        for path in sorted((pathlib.Path(root) / "benchmarks" / "perf_card").glob("cpu_card_*.json")):
            rows = json.loads(path.read_text())["memory"]["rows"]
            for row in rows:
                self.assertEqual(sync_cards.net_peak_bytes(row), cc.net_peak_bytes(row, "rk4_cpu"), (path.name, row["arm"]))
                self.assertEqual(sync_cards.published_peak_bytes(row, rows),
                                 cc.published_peak_bytes(row, rows, "rk4_cpu"), (path.name, row["arm"], row["n"]))
                checked += 1
        self.assertGreater(checked, 0)


class StartHereNotebookColabCell(unittest.TestCase):
    """The first code cell of the trial notebook installs itself on Colab and never carries a commented-out pip line."""

    def test_first_cell_has_colab_branch(self):
        nb = json.loads((SITE_ROOT / "notebooks" / "raptor_start_here.ipynb").read_text())
        cell = next(c for c in nb["cells"] if c["cell_type"] == "code")
        text = "".join(cell["source"])
        self.assertIn("google.colab", text)
        self.assertIn('extra = ""', text)                                             # GPU extras only with a GPU
        self.assertIn('extra = f"[cuda{major}]"', text)
        self.assertIn('f"raptor-hawk{extra}", f"raptor-eagle{extra}"', text)
        self.assertIn("sys.version_info", text)                                        # the Python range is checked up front
        self.assertIn("Runtime \u2192 Change runtime type \u2192 T4 GPU", text)
        for line in text.splitlines():
            self.assertFalse(line.lstrip().startswith(("# !pip", "#!pip", "# %pip")), line)


class FeatureBlock(unittest.TestCase):
    """The C2 block: rows of the feature card, with the A1 labels shown as they are."""

    def _eagle(self, tmp, rows):
        d = pathlib.Path(tmp) / "benchmarks" / "perf_card"
        d.mkdir(parents=True)
        card = {"device": {"name": "Test GPU"}, "rows": rows}
        (d / "feature_card_test.json").write_text(json.dumps(card))
        return pathlib.Path(tmp)

    def test_no_card_gives_an_empty_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, ok = sync_cards.build_feature_block(sync_cards.Pool(tmp), tmp)
        self.assertFalse(ok)
        self.assertNotIn("|", text)

    def test_labels_and_ratios(self):
        ok = lambda s: {"status": "ok", "wall_s": {"median": s}}  # noqa: E731
        rows = [{"row": "scatter", "n": 4194304, "dtype": "float64", "reference_arm": "keyed",
                 "arms": {"keyed": ok(0.002), "ordered": ok(0.004), "or": {"status": "out_of_memory"},
                          "np": {"status": "not_run: budget"}, "cupy": {"status": "failed: boom"},
                          "torch": {"status": "not_run: not installed: torch"}}}]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._eagle(tmp, rows)
            text, ok_ = sync_cards.build_feature_block(sync_cards.Pool(root), root)
        self.assertTrue(ok_)
        for expected in ("| ordered | 4.00 ms | 2.0x |", "out of memory", "> 120 s per run", "not installed", "| cupy | failed |"):
            self.assertIn(expected, text.replace("×", "x"))


class NewCardSchema(unittest.TestCase):
    """What the generator reads from the eagle 0.7.3 card format."""

    def test_the_headline_batch_is_one_million_when_the_card_has_it(self):
        self.assertEqual(sync_cards.top_n({"ns": [1000000, 10000000]}), 1000000)
        self.assertEqual(sync_cards.top_n({"ns": [1000, 2000]}), 2000)

    def test_a_loaded_card_has_configs_a_cpu_dict_and_only_timed_rows(self):
        pool = sync_cards.Pool(FIXTURE_EAGLE)
        cpu = sync_cards.load_card(pool, "benchmarks/perf_card/cpu_card_fixture-host.json")
        self.assertIsInstance(cpu["cpu"], dict)
        self.assertEqual(cpu["cpu"]["logical_cpus"], cpu["logical_cpus"])
        self.assertTrue(all("wall_s" in r for r in cpu["results"]))
        self.assertEqual([c["distribution"] for c in cpu["configs"]], cpu["distributions"])
        gpu = sync_cards.load_card(pool, "benchmarks/perf_card/card_fixture-gpu.json")
        for row in gpu["memory"]["rows"]:
            if row.get("device_peak_bytes") is not None and row.get("minimum_bytes"):
                self.assertEqual(row["device_factor"], row["device_peak_bytes"] / row["minimum_bytes"])

    def test_the_feature_block_follows_the_gpu_feature_card_and_labels_missing_arms(self):
        text = run_sync(FIXTURE_EAGLE, tempfile.mkdtemp())["feature_rows.md"]
        self.assertIn("each row is one capability at one batch size", text)
        self.assertIn("out of memory", text)

    def test_the_batch_phrases_name_what_the_cards_record(self):
        self.assertIn("own time", sync_cards._cfg_phrase("spread"))
        self.assertIn("same orbit", sync_cards._cfg_phrase("uniform"))

    def test_the_removed_blocks_are_not_written(self):
        out = run_sync(FIXTURE_EAGLE, tempfile.mkdtemp())
        self.assertNotIn("compaction_numbers.md", out)
        self.assertNotIn("landing_honest.md", out)


if __name__ == "__main__":
    unittest.main()
