# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The landing radar: scores, log scaling, best-arm pick, portability with a
missing device, the qualitative JSON, and the device data of every chip."""
import hashlib
import json
import pathlib
import re
import sys
import tempfile
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_cards as sc  # noqa: E402

FIXTURE_EAGLE = SITE_ROOT / "tests" / "fixtures" / "mini_eagle"
GENERATED = SITE_ROOT / "_generated"


def _card(walls, model=None, slug="x", rates=None):
    """A minimal perf card: spread S=1000 and uniform S=1000 at N=1000 and N=10.
    ``rates`` = {arm: (spread, uniform) sample_steps_per_s} adds that field to the arm's rows."""
    results = []
    for arm, w in walls.items():
        for dist in ("spread", "uniform"):
            for n in (10, 1000):
                row = {"arm": arm, "n": n, "distribution": dist, "max_steps": 1000, "wall_s": {"median": w}}
                if rates and arm in rates:
                    row["sample_steps_per_s"] = rates[arm][0 if dist == "spread" else 1]
                results.append(row)
    card = {"ns": [10, 1000], "arms": {a: a for a in walls}, "results": results, "device_slug": slug,
            "device": {"name": slug}}
    if model:
        card.pop("device")
        card["cpu"] = {"model": model, "cores": 1, "logical_cpus": 1}
    return card


class BestArmAndScores(unittest.TestCase):
    def test_tool_mapping_per_side(self):
        self.assertEqual(sc.radar_tool("eagle_graph", "gpu"), "raptor")
        self.assertIsNone(sc.radar_tool("eagle_cpu", "gpu"))        # host arm of a GPU card
        self.assertEqual(sc.radar_tool("eagle_cpu8", "cpu"), "raptor")
        self.assertEqual(sc.radar_tool("torch_graphed", "gpu"), "PyTorch")
        self.assertEqual(sc.radar_tool("numba_prange", "cpu"), "Numba")
        self.assertIsNone(sc.radar_tool("python_loops", "cpu"))

    def test_best_arm_pick_takes_the_smallest_per_tool(self):
        best = sc.best_arm_per_tool({"eagle_graph": 3.0, "eagle_simulate": 2.0, "warp_kernel": 4.0,
                                     "torch_masked": 9.0, "torch_graphed": 8.0, "eager_loop": 0.1}, "gpu")
        self.assertEqual(best["raptor"], ("eagle_simulate", 2.0))
        self.assertEqual(best["PyTorch"], ("torch_graphed", 8.0))
        self.assertNotIn("eager_loop", {a for a, _v in best.values()})

    def test_scores_are_best_over_value(self):
        s = sc.radar_scores({"raptor": ("a", 2.0), "JAX": ("b", 8.0)})
        self.assertEqual(s, {"raptor": 1.0, "JAX": 0.25})

    def test_non_positive_values_have_no_reading(self):
        self.assertEqual(sc.best_arm_per_tool({"warp_kernel": 0, "jax_vmap": None}, "gpu"), {})


class PerAxisScale(unittest.TestCase):
    def test_best_at_the_edge_worst_at_the_floor(self):
        span = sc.radar_axis_span([1.0, 3.0, 20.0])
        self.assertEqual(span, 20.0)
        self.assertAlmostEqual(sc.radar_radius(1.0, span), 1.0)
        self.assertAlmostEqual(sc.radar_radius(20.0, span), sc.RADAR_FLOOR)
        self.assertEqual(sc.RADAR_FLOOR, 0.2)

    def test_log_between_best_and_worst(self):
        span = 100.0
        self.assertAlmostEqual(sc.radar_radius(10.0, span), 0.6)       # geometric middle = 60%

    def test_minimum_span_does_not_magnify_noise(self):
        span = sc.radar_axis_span([1.0, 1.05])
        self.assertEqual(span, sc.RADAR_MIN_SPAN)
        self.assertGreater(sc.radar_radius(1.05, span), 0.9)           # nearly the edge, not the floor

    def test_never_the_centre(self):
        self.assertEqual(sc.radar_radius(float("inf"), 8.0), sc.RADAR_FLOOR)
        self.assertEqual(sc.radar_radius(1e9, 8.0), sc.RADAR_FLOOR)

    def test_77x_and_600x_leads_stay_apart(self):
        span = sc.radar_axis_span([1.0, 77.0, 600.0])
        self.assertGreater(sc.radar_radius(77.0, span), sc.radar_radius(600.0, span))
        self.assertGreater(sc.radar_radius(77.0, span), 0.3)

    def test_rubric_is_linear_floor_to_edge(self):
        self.assertAlmostEqual(sc.radar_radius_rubric(1, 1, 5), 0.2)
        self.assertAlmostEqual(sc.radar_radius_rubric(5, 1, 5), 1.0)
        self.assertAlmostEqual(sc.radar_radius_rubric(3, 1, 5), 0.6)

    def test_ring_labels_per_axis(self):
        self.assertEqual(sc.radar_ring_labels(4.0), "best · 2.0× · 4.0×")
        self.assertEqual(sc.radar_ring_labels(sc.RADAR_MIN_SPAN), "best · 1.4× · 2.0×")

    def test_score_spelling_floors_to_two_figures(self):
        self.assertEqual(sc._fmt_score(0.456), "0.45")
        self.assertEqual(sc._fmt_score(1.0), "1.0")


class Portability(unittest.TestCase):
    def test_worst_ratio_and_missing_device_counts_as_zero(self):
        gpu = _card({"eagle_graph": 1.0, "warp_kernel": 2.0, "jax_vmap": 10.0}, slug="g")
        gpu2 = _card({"eagle_graph": 1.0, "warp_kernel": 1.0, "jax_vmap": 4.0}, slug="g2")
        cpu = _card({"eagle_term8": 1.0, "numba_prange": 2.0, "jax_vmap": 5.0}, model="Cpu A")
        p = sc.radar_portability([("gpu", "g", gpu), ("gpu", "g2", gpu2), ("cpu", "Cpu A", cpu)])
        self.assertEqual(p["raptor"][0], 1.0)
        self.assertAlmostEqual(p["JAX"][0], 0.1)          # worst: 1/10 on g
        self.assertEqual(p["JAX"][1], "g")
        self.assertEqual(p["NVIDIA Warp"][0], 0.0)        # no reading on the CPU card
        self.assertEqual(p["NVIDIA Warp"][2], ["Cpu A"])
        self.assertEqual(p["Numba"][0], 0.0)              # no reading on either GPU card

    def test_a_card_with_no_data_is_not_a_device(self):
        p = sc.radar_portability([("gpu", "g", _card({"eagle_graph": 1.0})), ("gpu", "e", {"ns": []})])
        self.assertEqual(p["raptor"][2], [])


class Qualitative(unittest.TestCase):
    def test_json_loads_with_the_rubric_and_every_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sc.Pool(tmp)
            q = sc.load_qualitative(pool)
        axes = q["axes"]
        self.assertEqual(set(axes), {"tensor", "array_style", "half_precision", "control", "single_thread",
                                     "differentiable", "arrays", "deploy", "extensible"})
        self.assertIn("5 = this is its home ground.", axes["tensor"]["rubric"])
        scores = lambda k: {t: v["score"] for t, v in axes[k]["scores"].items()}  # noqa: E731
        self.assertEqual(scores("tensor"), {"PyTorch": 5, "JAX": 5, "CuPy": 4, "NumPy": 4,
                                            "NVIDIA Warp": 3, "raptor": 2, "Numba": 2})
        self.assertEqual(scores("differentiable"), {"PyTorch": 4, "JAX": 5, "NVIDIA Warp": 4, "CuPy": 1,
                                                    "raptor": 5, "NumPy": 1, "Numba": 1})
        self.assertEqual(scores("arrays"), {"PyTorch": 4, "JAX": 4, "NVIDIA Warp": 4, "CuPy": 5,
                                            "raptor": 5, "NumPy": 4, "Numba": 3})
        self.assertEqual(scores("deploy"), {"PyTorch": 4, "JAX": 4, "NVIDIA Warp": 2, "CuPy": 1,
                                            "raptor": 4, "NumPy": 1, "Numba": 2})
        self.assertEqual(scores("extensible"), {"JAX": 4, "PyTorch": 4, "raptor": 4, "Numba": 3,
                                                "NumPy": 3, "NVIDIA Warp": 2, "CuPy": 2})
        self.assertEqual(scores("array_style"), {"NumPy": 5, "CuPy": 5, "PyTorch": 5, "JAX": 4,
                                                 "Numba": 2, "NVIDIA Warp": 2, "raptor": 2})
        self.assertEqual(scores("half_precision"), {"PyTorch": 5, "JAX": 5, "CuPy": 3, "NVIDIA Warp": 3,
                                                    "NumPy": 2, "Numba": 2, "raptor": 1})
        self.assertIn("no BF16/FP8 or tensor-core path", axes["half_precision"]["scores"]["Numba"]["reason"])
        self.assertEqual(scores("single_thread"), {"raptor": 5, "JAX": 4, "NVIDIA Warp": 3, "PyTorch": 3,
                                                   "Numba": 3, "CuPy": 2, "NumPy": 1})
        self.assertEqual(axes["single_thread"]["label"], "Single-thread abstraction")
        self.assertIn("5 = you write one sample and nothing else.", axes["single_thread"]["rubric"])
        self.assertEqual(scores("control"), {"NVIDIA Warp": 5, "Numba": 5, "JAX": 3, "CuPy": 3,
                                             "PyTorch": 2, "raptor": 2, "NumPy": 1})
        for k in ("array_style", "half_precision", "control", "single_thread"):
            self.assertIn("Scores are the author's judgement.", axes[k]["rubric"])
            self.assertEqual(axes[k]["scale"], [1, 5])
        cpu = {t: v["score"] for t, v in axes["control"]["scores_cpu"].items()}
        self.assertEqual(cpu, {"JAX": 2, "NumPy": 2})
        for ax in axes.values():
            self.assertTrue(all(v["reason"] for v in ax["scores"].values()))
        self.assertIn("_data/radar_qualitative.json", pool.site_sources)

    def test_json_names_no_private_project(self):
        # private project names stay out of this repo too: the test holds their sha256 prefixes and hashes every
        # 4-6 letter substring of the file's words
        private = {"f951fea05900f8f8", "cf9b7fcf21302e45", "c48ac81fa0e9f6c3",
                   "802df9b957a46320", "dad256207b8b1652", "f51785d8f57e2d7c"}
        text = (SITE_ROOT / "_data" / "radar_qualitative.json").read_text().lower()
        for word in set(re.findall(r"[a-z]+", text)):
            for size in range(4, 7):
                for i in range(len(word) - size + 1):
                    digest = hashlib.sha256(word[i:i + size].encode()).hexdigest()[:16]
                    self.assertNotIn(digest, private, f"{word!r} contains a private project name")


SOL = 1.0e11   # a test device's R_SOL in sample-steps per second


class UnevenEfficiency(unittest.TestCase):
    """The uneven-batch efficiency: the spread-cell sample_steps_per_s over the device's R_SOL = F_dev / 22."""
    RATES = {"eagle_simulate": (4.7e10, 5e10), "warp_kernel": (1.8e10, 5e10), "jax_vmap": (6e8, 5e10)}

    def _gpu(self):
        return _card({"eagle_simulate": 1.0, "warp_kernel": 2.0, "jax_vmap": 10.0}, rates=self.RATES)

    def test_metric_is_the_spread_rate_over_the_speed_of_light(self):
        k = sc.uneven_eff(self._gpu(), "eagle_simulate", 1000, SOL)
        self.assertAlmostEqual(k["fraction"], 0.47)
        self.assertEqual((k["spread"], k["sol"]), (4.7e10, SOL))

    def test_a_missing_cell_or_field_gives_none(self):
        self.assertIsNone(sc.uneven_eff(_card({"eagle_simulate": 1.0}), "eagle_simulate", 1000, SOL))   # no rate field
        self.assertIsNone(sc.uneven_eff(self._gpu(), "no_such_arm", 1000, SOL))

    def test_percent_is_floored_never_rounded_up(self):
        self.assertEqual(sc._fmt_eff(0.479), "47%")
        self.assertEqual(sc._fmt_eff(0.4799999), "47%")
        self.assertEqual(sc._fmt_eff(0.5), "50%")
        self.assertEqual(sc._fmt_eff(0.0099), "<1%")
        self.assertEqual(sc._fmt_eff(0.01), "1%")

    def test_a_value_above_the_speed_of_light_fails_and_is_never_clamped(self):
        card = _card({"eagle_simulate": 1.0}, rates={"eagle_simulate": (1.1 * SOL, 1.1 * SOL)})   # a planted 110 % row
        with self.assertRaises(ValueError):
            sc.uneven_eff(card, "eagle_simulate", 1000, SOL)
        with self.assertRaises(ValueError):
            sc.check_rows_under_sol(card, SOL)
        sc.check_rows_under_sol(self._gpu(), SOL)       # the honest card passes

    def _root(self, tmp, entry):
        root = pathlib.Path(tmp)
        (root / "benchmarks").mkdir(parents=True)
        (root / "benchmarks" / "sol_reference.json").write_text(json.dumps(
            {"ops_per_step": 22, "aliases": {}, "devices": {"x": entry}}))
        return root

    def test_a_pending_device_shows_one_line_instead_of_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sc.Pool(self._root(tmp, {"source": "pending", "fma_per_s": None}))
            card = self._gpu()
            card["_reference_stem"] = "x"
            html_, vals = sc.eff_chart_html(pool, "gpu", card, 1000, sc.ARM_CHIP_VAR)
        self.assertEqual(vals, [])
        self.assertIn("Reference measurement pending for this device", html_)
        self.assertNotIn('class="row', html_)

    def test_a_device_without_any_reference_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sc.Pool(self._root(tmp, {"source": "spec", "fma_per_s": 22 * SOL}))
            card = self._gpu()
            card["_reference_stem"] = "other"
            with self.assertRaises(ValueError):
                sc.eff_chart_html(pool, "gpu", card, 1000, sc.ARM_CHIP_VAR)

    def test_the_reference_file_is_tracked_by_md5(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sc.Pool(self._root(tmp, {"source": "spec", "fma_per_s": 22 * SOL}))
            card = self._gpu()
            card["_reference_stem"] = "x"
            sc.eff_chart_html(pool, "gpu", card, 1000, sc.ARM_CHIP_VAR)
        self.assertIn("benchmarks/sol_reference.json", pool.sources)

    def test_the_radar_axis_scores_wall_time_on_the_spread_cell(self):
        ax = sc.build_radar_device("gpu", "g", self._gpu(), None, {}, _qual())["axes"]["uneven"]
        self.assertEqual(ax["tools"]["raptor"]["value"], "1.00 s")                 # the spread-cell wall, not a share kept
        self.assertGreater(ax["tools"]["raptor"]["r"], ax["tools"]["NVIDIA Warp"]["r"])
        self.assertGreater(ax["tools"]["NVIDIA Warp"]["r"], ax["tools"]["JAX"]["r"])
        self.assertNotIn("kept", ax["rl"])

    def test_the_axis_is_wall_time(self):
        axis = next(a for a in sc.RADAR_AXES if a[0] == "uneven")
        self.assertEqual(axis[1], "Uneven ensembles")
        self.assertEqual(sc.RADAR_AXIS_EXTRA["uneven"]["unit"], "time")

    def test_cpu_models_show_the_device_names_table_else_the_cards_own_string(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "benchmarks" / "perf_card").mkdir(parents=True)
            (root / "benchmarks" / "device_names.json").write_text(
                json.dumps({"cpu_card_named": {"name": "Display Name"}}))
            for stem in ("cpu_card_named", "cpu_card_other"):
                (root / "benchmarks" / "perf_card" / f"{stem}.json").write_text(
                    json.dumps({"cpu": {"model": "raw model", "cores": 1, "logical_cpus": 1}}))
            pool = sc.Pool(root)
            named = sc.load_card(pool, "benchmarks/perf_card/cpu_card_named.json")
            other = sc.load_card(pool, "benchmarks/perf_card/cpu_card_other.json")
        self.assertEqual(named["cpu"]["model"], "Display Name")
        self.assertEqual(other["cpu"]["model"], "raw model")

    def test_bars_view_has_one_bar_per_tool_best_first_longer_is_better(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = sc.Pool(self._root(tmp, {"source": "spec", "fma_per_s": 22 * SOL}))
            card = self._gpu()
            card["_reference_stem"] = "x"
            html_, vals = sc.eff_chart_html(pool, "gpu", card, 1000, sc.ARM_CHIP_VAR)
        self.assertEqual([a for a, _l, _v in vals], ["eagle_simulate", "warp_kernel", "jax_vmap"])
        self.assertIn("47%", html_)
        self.assertIn("<1%", html_)
        widths = [float(w) for w in re.findall(r'class="fill" style="width:([\d.]+)%', html_)]
        self.assertEqual(widths, sorted(widths, reverse=True))
        self.assertIn(sc.EFF_NOTE, html_)
        self.assertIn("mechanism.html#efficiency-on-uneven-batches", html_)

    def test_the_card_without_the_field_has_no_bars_view(self):
        pool = sc.Pool(FIXTURE_EAGLE)
        self.assertEqual(sc.eff_chart_html(pool, "gpu", _card({"eagle_simulate": 1.0}), 1000, sc.ARM_CHIP_VAR), ("", []))


class AxisOrder(unittest.TestCase):
    def test_known_best_order_of_a_tiny_case(self):
        sets = [{"t": {"a": 1.0, "b": 0.2, "c": 0.9, "d": 0.3}}]
        order, j = sc.radar_best_order(["a", "b", "c", "d"], sets)
        self.assertEqual(order, ["a", "c", "d", "b"])
        self.assertAlmostEqual(j, 0.8)

    def test_every_tool_counts_equally_and_missing_pairs_are_skipped(self):
        sets = [{"x": {"a": 1.0, "b": 0.5}, "y": {"a": 1.0, "c": 0.0}}]
        self.assertAlmostEqual(sc.radar_jaggedness(["a", "b", "c"], sets), 0.5)   # b-c has no tool with both

    def test_first_axis_is_fixed(self):
        order, _j = sc.radar_best_order(["a", "b", "c"], [{"t": {"a": 0.0, "b": 1.0, "c": 0.5}}])
        self.assertEqual(order[0], "a")

    def test_each_side_has_its_own_recorded_order_and_every_device_follows_it(self):
        src = json.loads((GENERATED / "SOURCES.json").read_text())["radar_order"]
        self.assertEqual(set(src), {"landing", "detailed"})
        for mode in src:
            self.assertEqual(set(src[mode]), {"gpu", "cpu"})
            for side in ("gpu", "cpu"):
                self.assertEqual(sorted(src[mode][side]["order"]), sorted(sc.RADAR_MODE_KEYS[mode]))
        text = (GENERATED / "radar_gpu.md").read_text()
        self.assertEqual([a["key"] for a in DeviceData._json(text)["axes"]], src["landing"]["gpu"]["order"])
        text = (GENERATED / "radar_cpu.md").read_text()
        self.assertEqual([a["key"] for a in DeviceData._json(text)["axes"]], src["landing"]["cpu"]["order"])
        for mode in src:
            for side in ("gpu", "cpu"):
                order = src[mode][side]["order"]
                pos = sorted(order.index(k) for k in sc.RADAR_ADJACENT_KEYS)
                self.assertEqual(pos, list(range(pos[0], pos[0] + 5)), (mode, side, order))
                self.assertEqual(len(sc.RADAR_ADJACENT_KEYS), 5)
                self.assertEqual(order.index("control") + 1 == order.index("single_thread")
                                 or order.index("single_thread") + 1 == order.index("control"), True,
                                 "single-thread abstraction sits next to low-level control")

    def test_cpu_order_is_computed_over_the_cpu_cards_only(self):
        cpu = {"t": {"a": 1.0, "b": 0.2, "c": 0.9, "d": 0.3}}
        gpu = {"t": {"a": 0.0, "b": 0.0, "c": 1.0, "d": 1.0}}
        only_cpu = sc.radar_best_order(["a", "b", "c", "d"], [cpu])[0]
        both = sc.radar_best_order(["a", "b", "c", "d"], [cpu] + [gpu] * 5)[0]
        self.assertEqual(only_cpu, ["a", "c", "d", "b"])
        self.assertNotEqual(only_cpu, both)                  # pooling the other side would change the order


class CodeSizeScale(unittest.TestCase):
    def test_22_vs_32_lines_stays_near_the_edge(self):
        span = sc.radar_axis_span([1.0, 32 / 22, 2.0], sc.RADAR_MIN_SPAN_BY_AXIS["code"])
        self.assertEqual(span, 4.0)                                        # a minimum span of 4x
        self.assertGreaterEqual(sc.radar_radius(32 / 22, span), 0.75)
        self.assertLess(sc.radar_radius(32 / 22, sc.RADAR_MIN_SPAN * 1.0), 0.75)   # the default 2x would not

    def test_the_rule_is_in_the_axis_description(self):
        text = (GENERATED / "radar_gpu.md").read_text()
        self.assertIn("spans at least 4x from best to worst", text)


class LandingGap(unittest.TestCase):
    def test_every_axis_is_evenly_spaced_and_there_is_no_divider_spoke(self):
        n = len(sc.RADAR_MODE_KEYS["landing"])
        self.assertEqual(n, 13)
        angles = [sc._axis_angle(i, n, "landing") for i in range(n)]
        step = 2 * 3.141592653589793 / n
        for a, b in zip(angles, angles[1:]):
            self.assertAlmostEqual(b - a, step)
        for name in ("radar_gpu.md", "radar_cpu.md"):
            text = (GENERATED / name).read_text()
            self.assertNotIn("radar-divider", text)
            self.assertNotIn('radar-spoke q', text)


class AxisIcons(unittest.TestCase):
    def test_every_axis_has_a_line_icon_in_the_grid(self):
        import radar_icons
        self.assertEqual({a[0] for a in sc.RADAR_AXES}, set(radar_icons.ICONS))
        for key, markup in radar_icons.ICONS.items():
            self.assertNotIn("stroke-width", markup, key)       # one stroke width, set once in the CSS
            self.assertNotIn("http", markup, key)               # inline, no external file

    def test_every_axis_icon_has_an_aria_label_with_its_direction(self):
        for name, mode in (("radar_gpu.md", "landing"), ("radar_cpu.md", "landing"), ("radar_detailed.md", "detailed")):
            text = (GENERATED / name).read_text()
            for key in sc.RADAR_MODE_KEYS[mode]:
                m = re.search(r'<g class="radar-icon disc"[^>]*data-axis="%s" aria-label="([^"]+)"' % key, text)
                self.assertTrue(m, (name, key))
                d = sc.RADAR_AXIS_EXTRA[key]["dir"]
                self.assertTrue(m.group(1).endswith(d if d else "a higher score is better"), (key, m.group(1)))
                self.assertIn('<symbol id="rico-', text)
        gpu = (GENERATED / "radar_gpu.md").read_text()
        self.assertIn("Uneven ensembles, faster is better", gpu)

    def test_the_phone_layout_swaps_names_and_ring_numbers_for_icons(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        m = re.search(r"@container \(max-width: 719px\) \{(.*?)\n\}", css, re.S)
        self.assertTrue(m)
        phone = m.group(1)
        self.assertNotIn("radar-num", css)                      # no ring numbers at any width
        for name in ("radar_gpu.md", "radar_cpu.md", "radar_detailed.md"):
            self.assertNotIn("radar-num", (GENERATED / name).read_text())
        self.assertRegex(phone, r"\.radar-icon\.disc \{ display: block; \}")
        self.assertRegex(phone, r"\.radar-axlist \.n \{ display: none; \}")
        # outside the phone layout the icons on the disc stay hidden
        self.assertRegex(css, r"\.radar-icon\.disc \{ display: none;")


class Palette(unittest.TestCase):
    """One categorical set, in the CSS only: contrast on the page and, within each set of tools shown
    together, a minimum difference under colour-vision deficiency."""
    TOOLS = ("raptor", "warp", "jax", "pytorch", "cupy", "numba", "numpy")
    SETS = {"gpu": ("raptor", "warp", "jax", "pytorch", "cupy"), "cpu": ("raptor", "numba", "jax", "pytorch", "numpy")}
    MACHADO = {
        "deut": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
        "prot": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
        "trit": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
    }

    @staticmethod
    def _lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    @staticmethod
    def _unlin(c):
        c = min(1.0, max(0.0, c))
        return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    def _rgb(self, h):
        return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def _lum(self, rgb):
        r, g, b = (self._lin(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _contrast(self, a, b):
        x, y = sorted((self._lum(self._rgb(a)), self._lum(self._rgb(b))), reverse=True)
        return (x + 0.05) / (y + 0.05)

    def _lab(self, rgb):
        r, g, b = (self._lin(c) for c in rgb)
        xyz = (0.4124 * r + 0.3576 * g + 0.1805 * b, 0.2126 * r + 0.7152 * g + 0.0722 * b,
               0.0193 * r + 0.1192 * g + 0.9505 * b)
        f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
        fx, fy, fz = f(xyz[0] / 0.95047), f(xyz[1]), f(xyz[2] / 1.08883)
        return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

    def _sim(self, rgb, kind):
        if kind == "norm":
            return rgb
        m = self.MACHADO[kind]
        lin = [self._lin(c) for c in rgb]
        return [self._unlin(sum(m[i][j] * lin[j] for j in range(3))) for i in range(3)]

    def _palette(self, theme):
        sys.path.insert(0, str(SITE_ROOT / "tools"))
        from palette import tool_palette
        return tool_palette(theme)

    def test_every_tool_has_one_token_per_theme_and_nowhere_else(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        for t in self.TOOLS:
            self.assertEqual(len(re.findall(rf"--tool-{t}:", css)), 2, t)

    def test_stroke_contrast_on_both_pages(self):
        for theme, bgs in (("light", ("#fcfcfb", "#ffffff")), ("dark", ("#1a1a19", "#242422"))):
            for tool, hexv in self._palette(theme).items():
                for bg in bgs:
                    self.assertGreaterEqual(self._contrast(hexv, bg), 3.0, f"{theme} {tool} on {bg}")

    def test_no_two_tools_shown_together_become_indistinguishable_under_cvd(self):
        import itertools
        for theme in ("light", "dark"):
            pal = self._palette(theme)
            for side, members in self.SETS.items():
                for kind in ("norm", "deut", "prot", "trit"):
                    for a, b in itertools.combinations(members, 2):
                        la, lb = (self._lab(self._sim(self._rgb(pal[x]), kind)) for x in (a, b))
                        d = sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5
                        self.assertGreaterEqual(d, 10.0, f"{theme} {side} {kind}: {a} vs {b} = {d:.1f}")

    def test_each_tool_keeps_its_brand_hue_family(self):
        import colorsys
        brand = {"warp": (60, 100), "jax": (160, 185), "pytorch": (0, 20), "cupy": (110, 145), "numba": (185, 210),
                 "numpy": (210, 235), "raptor": (250, 270)}
        for theme in ("light", "dark"):
            pal = self._palette(theme)
            for tool, (lo, hi) in brand.items():
                hue = colorsys.rgb_to_hls(*self._rgb(pal[tool]))[0] * 360
                self.assertTrue(lo <= hue <= hi, f"{theme} {tool}: hue {hue:.0f}")

    def test_cpu_radar_starts_with_numpy_off(self):
        text = (GENERATED / "radar_cpu.md").read_text()
        self.assertRegex(text, r'data-tool="NumPy" aria-pressed="false"')
        self.assertIn('class="radar-tool is-off" data-tool="NumPy"', text)
        self.assertEqual(text.count('aria-pressed="true"'), 4)
        gpu = (GENERATED / "radar_gpu.md").read_text()
        self.assertNotIn('aria-pressed="false"', gpu)


class Direction(unittest.TestCase):
    def test_every_measured_axis_says_which_way_is_better_and_marks_its_edge(self):
        text = (GENERATED / "radar_gpu.md").read_text()
        for phrase in ("faster is better", "lower is better", "smaller is better", "higher is better"):
            self.assertIn(phrase, text)
        for word in (">fastest<", ">smallest<", ">best<"):
            self.assertNotIn(word, text)                                   # edge words live in the tooltip and panel
        self.assertIn('"edge":"fastest"', text)
        self.assertIn('class="radar-tick"', text)
        self.assertIn("Axes are ordered so each tool's strengths sit together", text)

    def test_detailed_is_one_even_ring_with_short_labels_and_a_list_for_narrow_columns(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        for phrase in (">Derivatives<", ">Your arrays<", ">Deploy<", ">Extensibility<", ">Tensors<", 'class="radar-axlist"'):
            self.assertIn(phrase, text)
        for gone in ("Measured on the cards", "Ecosystem (rubric)", "radar-divider", "radar-title"):
            self.assertNotIn(gone, text)
        n = len(sc.RADAR_MODE_KEYS["detailed"])
        step = 2 * 3.141592653589793 / n
        angles = [sc._axis_angle(i, n, "detailed") for i in range(n)]
        for a, b in zip(angles, angles[1:]):
            self.assertAlmostEqual(b - a, step)
        spokes = re.findall(r'<line class="radar-spoke"', text)
        self.assertEqual(len(spokes), 2 * n)                    # one per axis, for each of the two sides


class SingleThreadNextToUneven(unittest.TestCase):
    """The order search is constrained so the qualitative group ends ``control, single_thread``:
    Single-thread abstraction is adjacent to the first measured axis (Uneven ensembles) around the ring."""
    def test_the_order_ends_with_the_tail_and_wraps_to_uneven(self):
        src = json.loads((GENERATED / "SOURCES.json").read_text())["radar_order"]
        for mode in ("landing", "detailed"):
            for side in ("gpu", "cpu"):
                order = src[mode][side]["order"]
                self.assertEqual(order[0], "uneven", (mode, side))
                self.assertEqual(order[-2:], list(sc.RADAR_GROUP_TAIL), (mode, side))
                pos = sorted(order.index(k) for k in sc.RADAR_ADJACENT_KEYS)
                self.assertEqual(pos, list(range(pos[0], pos[0] + 5)), (mode, side))   # the five stay adjacent

    def test_the_constraint_is_in_the_search(self):
        sets = [{"t": {"a": 0.2, "b": 1.0, "c": 0.3, "d": 0.9}}]
        order, _j = sc.radar_best_order(["a", "b", "c", "d"], sets, tail=("b", "d"))
        self.assertEqual(order[-2:], ["b", "d"])
        order, _j = sc.radar_best_order_grouped(["x", "a", "b", "c"], ["a", "b", "c"], sets, tail=("c",))
        self.assertEqual(order[-1], "c")


def _compile_cards():
    perf = _card({"eagle_graph": 1.0, "torch_masked": 2.0, "torch_compiled": 3.0, "jax_vmap": 3.0, "warp_kernel": 4.0})
    perf["memory"] = {"rows": []}
    perf["code"] = {"arms": {}}
    cold = lambda s: {"cold_s": {"median": s}, "warm_s": {"median": s / 10}}  # noqa: E731
    perf["compile_time"] = {"rows": [
        {"arms": ["eagle_graph"], "key": "eagle:g", **cold(2.0)},
        {"arms": ["jax_vmap"], "key": "jax:10", **cold(9.0)}, {"arms": ["jax_vmap"], "key": "jax:1000", **cold(1.0)},
        {"arms": ["torch_compiled"], "key": "torch:1000", **cold(7.0)},
        {"arms": ["warp_kernel"], "key": "warp", **cold(0.5)}], "none": ["torch_masked"]}
    rk = {"ns": [10, 1000], "arms": {"eagle_graph": "g", "jax_vmap": "j", "warp_kernel": "w"}, "results": [],
          "compile_time": {"rows": [
              {"arms": ["eagle_graph"], "key": "hawk_cuda", **cold(6.0)},
              {"arms": ["jax_vmap"], "key": "jax:10", **cold(99.0)}, {"arms": ["jax_vmap"], "key": "jax:1000", **cold(16.0)},
              {"arms": ["warp_kernel"], "key": "warp", **cold(0.1)}]}}
    return perf, rk


class CompileAxis(unittest.TestCase):
    def test_fixed_scale_edge_floor_and_clamp(self):
        r = sc.radar_radius_compile
        self.assertEqual(r(0.1), 1.0)
        self.assertEqual(r(0.01), 1.0)                       # faster than the edge clamps to it
        self.assertAlmostEqual(r(100.0), sc.RADAR_FLOOR)
        self.assertEqual(r(1000.0), sc.RADAR_FLOOR)
        self.assertAlmostEqual(r(sc.math.sqrt(0.1 * 100.0)), 0.6)    # geometric middle
        self.assertEqual(sc.radar_compile_rings(), "0.1 s · 3.2 s · 100 s")

    def test_the_scale_is_the_same_on_every_device(self):
        perf, rk = _compile_cards()
        a = sc.build_radar_device("gpu", "a", perf, rk, {}, _qual())["axes"]["compile"]["tools"]["raptor"]["r"]
        perf["compile_time"]["rows"][3]["cold_s"]["median"] = 0.2   # another tool getting faster changes nothing
        b = sc.build_radar_device("gpu", "b", perf, rk, {}, _qual())["axes"]["compile"]["tools"]["raptor"]["r"]
        self.assertEqual(a, b)
        self.assertAlmostEqual(a, sc.radar_radius_compile(6.0))

    def test_value_is_the_complex_kernel_largest_n_with_simple_and_growth_in_the_detail(self):
        perf, rk = _compile_cards()
        tools = sc.build_radar_device("gpu", "x", perf, rk, {}, _qual())["axes"]["compile"]["tools"]
        self.assertEqual(tools["raptor"]["value"], "6.00 s")
        self.assertIn("simple kernel 2.00 s, 3.0× from the simple to the adaptive kernel", tools["raptor"]["detail"])
        self.assertEqual(tools["JAX"]["value"], "16.0 s")                   # the largest-N row (1000), not N = 10
        self.assertIn("recompiles for every shape", tools["JAX"]["detail"])
        self.assertFalse(tools["raptor"]["hollow"])

    def test_pytorch_falls_back_to_torch_compile_hollow_and_is_never_no_compile_step(self):
        perf, rk = _compile_cards()
        tools = sc.build_radar_device("gpu", "x", perf, rk, {}, _qual())["axes"]["compile"]["tools"]
        pt = tools["PyTorch"]
        self.assertEqual(pt["value"], "7.00 s")                              # torch.compile, not the eager arm
        self.assertTrue(pt["hollow"])
        self.assertIn("simple kernel only: the adaptive card has no torch.compile arm", pt["detail"])
        self.assertNotEqual(pt["value"], "no compile step")

    def test_pytorch_without_a_torch_compile_arm_has_no_vertex_rather_than_no_compile_step(self):
        perf, rk = _compile_cards()
        perf["compile_time"]["rows"] = [r for r in perf["compile_time"]["rows"] if r["arms"] != ["torch_compiled"]]
        tools = sc.build_radar_device("gpu", "x", perf, rk, {}, _qual())["axes"]["compile"]["tools"]
        self.assertNotIn("PyTorch", tools)

    def test_a_tool_without_an_adaptive_reading_falls_back_hollow_and_labelled(self):
        perf, _rk = _compile_cards()
        tools = sc.build_radar_device("gpu", "x", perf, None, {}, _qual())["axes"]["compile"]["tools"]
        self.assertTrue(all(v["hollow"] for v in tools.values()))
        self.assertIn("no adaptive-kernel compile reading", tools["raptor"]["detail"])
        self.assertEqual(tools["raptor"]["value"], "2.00 s")

    def test_a_tool_with_genuinely_no_compile_step_sits_at_the_edge(self):
        perf = _card({"eagle_term8": 1.0, "numpy_masked": 2.0}, model="Cpu")
        perf["memory"] = {"rows": []}
        perf["code"] = {"arms": {}}
        perf["compile_time"] = {"rows": [{"arm": "eagle_term8", "key": "step", "cold_s": {"median": 1.0}, "warm_s": {"median": 0.1}}],
                                "none": ["numpy_masked"]}
        tools = sc.build_radar_device("cpu", "c", perf, None, {}, _qual())["axes"]["compile"]["tools"]
        self.assertEqual(tools["NumPy"]["r"], 1.0)
        self.assertEqual(tools["NumPy"]["value"], "no compile step")

    def test_bands_and_the_panel_wording(self):
        self.assertEqual(sc.radar_compile_band(0.5), "under 1 s: instant")
        self.assertEqual(sc.radar_compile_band(3), "1-10 s: noticeable")
        self.assertEqual(sc.radar_compile_band(70), "over 60 s: breaks interactive use")
        text = (GENERATED / "radar_detailed.md").read_text()
        self.assertIn("fixed scale: 0.1 s at the edge, 100 s at the floor", text)
        self.assertIn("Compiled once per kernel; raptor's compile does not depend on the problem size N.", text)
        self.assertIn("breaks interactive use", text)

    def test_rubric_text_is_collapsed_on_the_detailed_radar(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        self.assertIn("<summary>How to read this radar</summary>", text)


class RadarNotes(unittest.TestCase):
    """The notes under a radar: one visible sentence, the rest behind "How to read this radar"."""
    PAGES = ("radar_gpu.md", "radar_cpu.md", "radar_detailed.md")

    def test_one_visible_sentence_then_the_caption_and_a_collapsed_disclosure(self):
        for page in self.PAGES:
            text = (GENERATED / page).read_text()
            for block in re.split(r'(?=<div class="radar(?: radar-detailed)?" data-side)', text)[1:]:
                visible = re.sub(r"<details.*?</details>", "", block, flags=re.S)
                notes = re.findall(r'<p class="axis-note radar-note[^"]*">(.*?)</p>', visible, re.S)
                self.assertEqual(len(notes), 2, page)                           # the sentence and the Warp/control caption
                self.assertIn("hover or tap an axis for its meaning", notes[0])
                self.assertIn("qualitative scores (author's judgement)", notes[0])
                self.assertLessEqual(len(re.findall(r"[.;]\s", notes[1] + " ")), 2)
                self.assertIn("NVIDIA Warp gives you near-total control", notes[1])
                self.assertIn("Show the data behind the radar", block)
                self.assertIn('<details class="radar-data radar-howto">', block)    # collapsed: no `open`

    def test_the_disclosure_has_one_short_line_per_qualitative_axis(self):
        qual = json.loads((SITE_ROOT / "_data" / "radar_qualitative.json").read_text())["axes"]
        for k, ax in qual.items():
            self.assertRegex(ax["anchor"], r"^5 = ")
            self.assertLessEqual(len(ax["anchor"].split()), 15, k)
        for page, keys in (("radar_gpu.md", 5), ("radar_detailed.md", 9)):
            text = (GENERATED / page).read_text()
            for how in re.findall(r'<details class="radar-data radar-howto">(.*?)</details>', text, re.S):
                self.assertEqual(how.count("<li>"), keys, page)
                for item in re.findall(r"<li>(.*?)</li>", how):
                    self.assertLessEqual(len(re.sub(r"<[^>]+>", "", item).split()), 20)

    def test_the_full_rubric_stays_in_the_data_file(self):
        qual = json.loads((SITE_ROOT / "_data" / "radar_qualitative.json").read_text())["axes"]
        self.assertTrue(all(len(a["rubric"]) > len(a["anchor"]) for a in qual.values()))


def _qual():
    return {"axes": {k: {"rubric": k, "scale": [1, 5], "scores": {"raptor": {"score": 3, "reason": "r"}}}
                     for k in ("tensor", "array_style", "half_precision", "control", "single_thread")}}


class DeviceData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (GENERATED / "radar_gpu.md").read_text()
        cls.gpu_text = text
        cls.gpu = cls._json(text)
        cls.cpu_text = (GENERATED / "radar_cpu.md").read_text()
        cls.cpu = cls._json(cls.cpu_text)
        cls.detailed_text = (GENERATED / "radar_detailed.md").read_text()
        blocks = re.findall(r'<script type="application/json" class="radar-json">.*?</script>', cls.detailed_text, re.S)
        cls.detailed_gpu = cls._json(blocks[0])
        cls.detailed_cpu = cls._json(blocks[1])

    @staticmethod
    def _json(text):
        return json.loads(re.search(r'class="radar-json">(.*?)</script>', text, re.S).group(1).replace("<\\/", "</"))

    def test_every_device_chip_has_radar_data(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        for side, data in (("gpu", self.gpu), ("cpu", self.cpu)):
            slugs = re.findall(rf'name="perf-{side}" id="perf-{side}-\d+" data-slug="([^"]+)"', switch)
            self.assertTrue(slugs)
            self.assertEqual(set(slugs), set(data["devices"]))

    def test_every_device_chip_has_the_bars_toggle(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        panels = re.findall(r'<section class="perf-dev">(.*?)</section>', switch, re.S)
        chips = len(re.findall(r'name="perf-(?:gpu|cpu)" id="perf-(?:gpu|cpu)-\d+"', switch))
        self.assertEqual(len(panels), chips)
        for p in panels:
            self.assertEqual(p.count('class="bars-toggle"'), 1)
            self.assertEqual(p.count('aria-pressed="true">Wall time<'), 1)
            self.assertEqual(p.count('aria-pressed="false">Uneven-batch efficiency<'), 1)
            self.assertIn('class="bars-view bars-wall"', p)
            self.assertIn('class="bars-view bars-eff"', p)
            self.assertTrue(sc.EFF_NOTE in p or sc.EFF_PENDING in p)
            self.assertNotIn("kept", p.lower())

    def test_toggle_state_is_remembered_with_guarded_storage(self):
        js = (SITE_ROOT / "_static" / "js" / "perf-state.js").read_text()
        self.assertRegex(js, r"try \{ saved = window\.localStorage\.getItem")
        self.assertRegex(js, r"try \{ window\.localStorage\.setItem")
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn(".bars-opt:focus-visible", css)

    def test_sources_json_carries_the_uneven_efficiency(self):
        data = json.loads((GENERATED / "SOURCES.json").read_text())
        self.assertNotIn("uneven_kept", data)
        self.assertIn("benchmarks/sol_reference.json", {x["path"] for x in data["sources"]})
        src = data["uneven_efficiency"]
        h100 = src["gpu"]["nvidia-h100-80gb-hbm3"]["tools"]
        self.assertEqual(set(h100), {"raptor", "NVIDIA Warp", "JAX", "PyTorch", "CuPy"})
        self.assertTrue(all(0 < v["efficiency_percent"] <= 100 and v["arm"] for v in h100.values()))
        self.assertIn("amd-epyc-9b45", src["cpu"])
        self.assertIn("raptor", src["cpu"]["aarch64"]["tools"])                   # its reference is measured
        self.assertIn("raptor", src["cpu"]["amd-epyc-7b13"]["tools"])

    def test_a_cpu_with_a_measured_reference_shows_no_pending_line(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        self.assertEqual(switch.count("Reference measurement pending for this device"), 0)

    def test_the_h100_efficiency_view_is_floored(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        view = re.search(r'aria-label="Uneven-batch efficiency on NVIDIA H100 80GB HBM3: ([^"]+)"', switch).group(1)
        self.assertRegex(view, r"eagle\.simulate 47%, NVIDIA Warp 18%, JAX <1%")

    def test_site_efficiency_equals_eagles_for_every_gpu_card(self):
        """The site's value is eagle's own ``eff`` span (tools/prose_claims.py) for the same arm, card and cell."""
        import importlib.util
        import os
        root = os.environ.get("RAPTOR_EAGLE_ROOT")
        if not root or not (pathlib.Path(root) / "tools" / "prose_claims.py").is_file():
            self.skipTest("no eagle root (RAPTOR_EAGLE_ROOT)")
        root = pathlib.Path(root)
        spec = importlib.util.spec_from_file_location("eagle_prose_claims", root / "tools" / "prose_claims.py")
        pcl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pcl)

        class OneCard:                      # eagle's card loader, pinned to one file
            def __init__(self, path):
                self.root, self._path = root, path

            def path(self, _card, _dev):
                return self._path

            def load(self, _card, _dev):
                return json.loads(self._path.read_text())

        pool = sc.Pool(root)
        checked = 0
        for kind, prefix, card_key in (("gpu", "card_", "rk4"), ("cpu", "cpu_card_", "rk4cpu")):
            for path in sorted((root / "benchmarks" / "perf_card").glob(f"{prefix}*.json")):
                card = sc.load_card(pool, path.relative_to(root))
                card["_reference_stem"] = path.stem[len(prefix):]
                got = sc.eff_values(pool, kind, card)
                if got is None:
                    continue
                _key, _entry, vals = got
                for arm, _label, v in vals:
                    tool = next(t for t, pre, _b in sc.EFF_TOOLS[kind] if arm.startswith(pre))
                    if tool not in pcl.TOOL_ARMS:
                        continue                    # eagle's eff spans cover eagle, warp, jax, torch, cupy
                    sel = {"card": card_key, "dev": "x", "tool": tool, "dist": "spread", "steps": "1000"}
                    theirs = pcl.efficiency(OneCard(path), sel)
                    self.assertAlmostEqual(v["fraction"], theirs, places=12, msg=f"{path.name} {arm}")
                    self.assertEqual(sc._fmt_eff(v["fraction"]), pcl.fmt_eff(theirs))
                    checked += 1
        self.assertGreater(checked, 20)

    def test_switch_embeds_each_radar(self):
        switch = (GENERATED / "perf_switch.md").read_text()
        self.assertEqual(switch.count('class="radar" data-side='), 2)

    def test_default_device_is_first_and_every_axis_has_a_label(self):
        self.assertEqual(len(self.gpu["axes"]), 13)
        self.assertEqual(len(self.detailed_gpu["axes"]), 17)
        self.assertEqual(list(self.gpu["devices"])[0], "nvidia-h100-80gb-hbm3")

    def test_portability_is_the_same_on_every_tab(self):
        vals = {slug: d["tips"]["raptor"]["portability"]["v"] for slug, d in self.gpu["devices"].items()}
        self.assertEqual(len(set(vals.values())), 1)

    def test_missing_reading_has_no_vertex(self):
        # the P2000 has no compile-time reading for some tool in the committed set
        # (torch.compile needs cc >= 7.0): no vertex, not a zero
        p2000 = self.gpu["devices"]["quadro-p2000"]
        compile_axis = [i for i, a in enumerate(self.gpu["axes"]) if a["key"] == "compile"][0]
        missing = [tool for tool in p2000["pts"] if str(compile_axis) not in p2000["pts"][tool]]
        self.assertTrue(missing)
        for tool in missing:
            self.assertNotIn("compile", p2000["tips"][tool])

    def test_qualitative_axis_is_marked(self):
        self.assertIn('class="radar-axis q"', self.gpu_text)
        self.assertNotIn('class="radar-spoke q"', self.gpu_text)
        self.assertIn("font-style: italic", (SITE_ROOT / "_static" / "custom.css").read_text())
        self.assertIn("not measurements", self.gpu_text)

    def test_accessibility_hooks(self):
        self.assertIn('role="img" aria-label="Where each tool shines on NVIDIA H100 80GB HBM3', self.gpu_text)
        self.assertEqual(self.gpu_text.count('aria-pressed="true"'), 4)
        self.assertIn("<details class=\"radar-data\">", self.gpu_text)
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn(".radar-leg:focus-visible", css)
        js = (SITE_ROOT / "_static" / "js" / "radar.js").read_text()
        self.assertIn("prefers-reduced-motion", js)

    def test_ring_labels_are_per_axis_and_per_device(self):
        l4 = self.gpu["devices"]["nvidia-l4"]["rl"]
        self.assertEqual(l4["tensor"], "5 · 3 · 1")
        self.assertRegex(l4["uneven"], r"^[\d.]+ m?s · [\d.]+ m?s · [\d.]+ m?s$")      # real units, edge first
        # the edge label is the best tool's own value, whatever the card currently says
        tips = {tool: tip["uneven"] for tool, tip in self.gpu["devices"]["nvidia-l4"]["tips"].items()}
        edge = [t["v"] for t in tips.values() if t["r"].startswith("1.0×")]
        self.assertEqual(edge, [l4["uneven"].split(" · ")[0]])
        self.assertRegex(l4["memory"], r"^\d+ · \d+ · \d+ MiB$")
        self.assertRegex(l4["code"], r"^\d+ · \d+ · \d+ lines$")
        self.assertTrue(l4["portability"].startswith("best · "))                                # a pure ratio axis
        self.assertNotEqual(l4["small"], l4["code"])
        self.assertNotIn("radar-ring-label", self.gpu_text)               # units only on hover (script)
        self.assertNotIn("data-ring", self.gpu_text)

    def test_detailed_radar_has_every_tool_and_a_panel(self):
        self.assertEqual([t["id"] for t in self.detailed_gpu["tools"]],
                         ["raptor", "NVIDIA Warp", "JAX", "PyTorch", "CuPy"])
        self.assertEqual([t["id"] for t in self.detailed_cpu["tools"]],
                         ["raptor", "Numba", "JAX", "PyTorch", "NumPy"])
        self.assertIn('class="radar-panel"', self.detailed_text)
        self.assertEqual(self.detailed_text.count('aria-pressed="true"'), 9)
        self.assertEqual(self.detailed_text.count('aria-pressed="false"'), 1)               # NumPy, off by default
        self.assertEqual(set(self.detailed_gpu["devices"]), set(self.gpu["devices"]))
        for ax in self.detailed_gpu["axes"]:
            self.assertTrue(ax["src"])
        self.assertTrue(all(d["link"].startswith("https://") for d in self.detailed_gpu["devices"].values()))

    def test_detailed_switch_shares_the_hash_markup(self):
        self.assertIn('class="perf-switch perf-detailed"', self.detailed_text)
        self.assertIn('data-slug="nvidia-l4"', self.detailed_text)
        self.assertIn('data-side="cpu"', self.detailed_text)

    def test_the_page_includes_the_detailed_radar_and_keeps_the_message(self):
        page = (SITE_ROOT / "where_raptor_fits.md").read_text()
        self.assertIn("_generated/radar_detailed.md", page)
        self.assertNotIn("where_raptor_fits_light.svg", page)
        self.assertIn("complementary, not a ranking", self.detailed_text)

    def test_cpu_radar_draws_the_cpu_tools(self):
        self.assertEqual([t["id"] for t in self.cpu["tools"]], ["raptor", "Numba", "JAX", "PyTorch", "NumPy"])

    def test_tool_colours_are_site_tokens(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        for side in (self.gpu, self.cpu):
            for t in side["tools"]:
                self.assertIn(t["color"] + ":", css)


class FixtureBuild(unittest.TestCase):
    def test_sources_json_tracks_the_qualitative_md5(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = sc.main([str(FIXTURE_EAGLE), "--out-dir", tmp])
            self.assertEqual(rc, 0)
            src = json.loads((pathlib.Path(tmp) / "SOURCES.json").read_text())
        paths = {s["path"]: s["md5"] for s in src["site_sources"]}
        self.assertEqual(paths["_data/radar_qualitative.json"],
                         sc._md5(SITE_ROOT / "_data" / "radar_qualitative.json"))

    def test_the_visible_numbers_come_from_sources(self):
        sources = set(json.loads((GENERATED / "SOURCES.json").read_text())["numbers"])
        text = (GENERATED / "radar_gpu.md").read_text()
        text = re.sub(r'<svg.*?</svg>', " ", text, flags=re.S)
        text = re.sub(r'<script.*?</script>', " ", text, flags=re.S)
        text = re.sub(r"(?s)<em>.*?</em>|<style.*?</style>", " ", text)
        text = re.sub(r"(RK|aria-\w+=)\S*|data-\S+|class=\S+|style=\"[^\"]*\"", " ", text)
        missing = {m for m in sc._NUM_RE.findall(text) if m.rstrip('.') not in sources}
        self.assertFalse(missing, sorted(missing))


if __name__ == "__main__":
    unittest.main()
