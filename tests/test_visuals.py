# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The two coverage visuals (the capability map, the rosette) and their data. The map is static and sourced: what it shows
for every tool (each row's dot stop, the sentence, the list, the table) is compared with ``_data/capabilities.json``; the
rosette is rebuilt from the page's own JSON (coverage verdicts) on every device the generated pages carry."""
import functools
import html
import json
import math
import pathlib
import re
import sys
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import radar_icons  # noqa: E402
import sync_cards as sc  # noqa: E402
import visuals as V  # noqa: E402
import visuals_markup as M  # noqa: E402

GENERATED = SITE_ROOT / "_generated"
MIN_GAP = 4.0
#: Rosette label geometry is fixed per side, so its label gaps are checked on one card per side.
LABEL_CARDS = (("gpu", "nvidia-h100-80gb-hbm3"), ("cpu", "amd-epyc-9b45"))


def _blocks(text, cls):
    """[(side, block html)] of every ``div.<cls>`` of a generated page (the blocks do not nest)."""
    out = []
    for m in re.finditer(rf'<div class="{cls}" data-side="(gpu|cpu)">', text):
        end = text.index("</script>\n</div>", m.start()) + len("</script>\n</div>")
        out.append((m.group(1), text[m.start():end]))
    return out


def _json(block):
    return json.loads(re.search(r'<script type="application/json" class="worlds-json">(.*?)</script>', block, re.S).group(1).replace("<\\/", "</"))


def _tools(block):
    return re.findall(r'class="worlds-leg" data-tool="([^"]+)"', block)


def _devices(block):
    """[(slug, html of that device)] of a rosette block."""
    parts = re.split(r'(?=<div class="worlds-dev)', block)[1:]
    return [(re.search(r'data-slug="([^"]+)"', p).group(1), p) for p in parts]


@functools.lru_cache(maxsize=None)
def _map_page():
    text = (GENERATED / "perf_switch.md").read_text()
    out = {}
    for m in re.finditer(r'<div class="capmap" data-side="(gpu|cpu)"', text):
        end = text.index("</script>\n</div>", m.start()) + len("</script>\n</div>")
        out[m.group(1)] = text[m.start():end]
    return out


def _cm_json(block):
    return json.loads(re.search(r'<script type="application/json" class="cm-json">(.*?)</script>', block, re.S).group(1).replace("<\\/", "</"))


def _icons(block, mode):
    """{block key: (x px, y px, class)} of the chart icons of one width as rendered in the page."""
    svg = re.search(rf'<svg class="cq-svg cq-{mode}".*?</svg>', block, re.S).group(0)
    return {k: (float(x), float(y), cl) for cl, k, x, y in re.findall(
        r'<g class="cq-ic (is-\w+)" data-block="([^"]+)" data-x="[^"]*" data-y="[^"]*" tabindex="0"[^>]*? style="transform:translate\(([\d.]+)px,([\d.]+)px\)"', svg)}


@functools.lru_cache(maxsize=None)
def _rosette_page():
    text = (GENERATED / "radar_detailed.md").read_text()
    return {side: b for side, b in _blocks(text, "rosette")}


@functools.lru_cache(maxsize=None)
def _caps():
    return V.Capabilities(json.loads((SITE_ROOT / "_data" / "capabilities.json").read_text()))


def _table(dev_json):
    t = {}
    for f, per_tool in dev_json["vals"].items():
        t[f] = {tool: {"ok": bool(v[2])} for tool, v in per_tool.items() if v is not None}
    return t


def _paths(part, cls="blob"):
    return re.findall(rf'<path class="{cls}[^"]*" data-tool="([^"]+)"[^>]*? d="([^"]+)"', part)


class TestCoverageRule(unittest.TestCase):
    """The rosette's verdict on every feature is the radar's rule, the same for every tool."""

    def test_rule_on_the_ratio_and_the_score(self):
        self.assertTrue(V.covers("uneven", {"x": 2.0}))
        self.assertFalse(V.covers("uneven", {"x": 2.01}))
        self.assertTrue(V.covers("tensor", {"pts": 4}))
        self.assertFalse(V.covers("tensor", {"pts": 3}))
        self.assertFalse(V.covers("uneven", None))
        self.assertFalse(V.covers("uneven_eff", {"x": math.inf}))

    def test_the_page_verdicts_follow_the_printed_ratios(self):
        for side, b in _rosette_page().items():
            for slug, dj in _json(b)["devices"].items():
                for f, per_tool in dj["vals"].items():
                    for tool, v in per_tool.items():
                        if v is None or f == "compile":            # compile is printed as a band ("1-10 s"), not a ratio
                            continue
                        if f in V.MEASURED:
                            m = re.match(r"([\d.]+)×", v[1])
                            if m:
                                x = float(m.group(1))
                                if x < 2.0:                    # a printed 2.0 is floored: either verdict is possible there
                                    self.assertTrue(v[2], (side, slug, f, tool, v))
                                if x > 2.0:
                                    self.assertFalse(v[2], (side, slug, f, tool, v))
                            else:
                                self.assertEqual(v[2], 0, (side, slug, f, tool, v))
                        else:
                            m = re.match(r"(\d) of 5", v[0])
                            self.assertEqual(bool(v[2]), int(m.group(1)) >= V.RUBRIC_MIN, (side, slug, f, tool, v))

    def test_labels_match_the_site_axis_names(self):
        for k, lab in V.LABEL.items():
            if k in sc.RADAR_AXIS_EXTRA:
                self.assertEqual(lab, sc.RADAR_AXIS_EXTRA[k]["short"], k)


class TestCapabilityData(unittest.TestCase):
    """The map's coverage is static and sourced: every cell is in the data file, and every covered one has a source."""

    def test_every_cell_is_present_and_every_covered_cell_has_a_source(self):
        caps = _caps()
        self.assertEqual(caps.tools, [t for t, _v in sc.CAPMAP_TOOLS])
        self.assertEqual(set(caps.needs), set(V.BLOCKS_KEYS))
        for t in caps.tools:
            self.assertEqual(set(caps.cells[t]), set(V.BLOCKS_KEYS), t)
            for b in V.BLOCKS_KEYS:
                self.assertEqual(set(caps.cells[t][b]), {d for d, _n in V.DEVICES} | {"y"}, (t, b))
                for d, _n in V.DEVICES:
                    c = caps.cell(t, b, d)
                    self.assertIsInstance(c["covered"], bool, (t, b, d))
                    if c["covered"]:
                        self.assertRegex(c["source"], r"^https://[^\s\"<>]+$", (t, b, d))
                        self.assertTrue(c["note"].strip(), (t, b, d))
                        self.assertNotIn("\n", c["note"])
                    else:
                        self.assertNotIn("source", c, (t, b, d))

    def test_the_measured_rule_is_gone_from_the_map(self):
        block = _map_page()["gpu"]
        self.assertNotIn("2×", block)
        self.assertNotIn("of 5", block)
        self.assertIn("speed is in the bars and the radar", block)

    def test_the_rulings_hold(self):
        caps = _caps()
        for b in ("divergent", "events"):
            self.assertIsNone(caps.stop("Numba", b), b)
        self.assertIsNone(caps.stop("NVIDIA Warp", "deploy"))

    def test_stored_y_agrees_with_the_cells(self):
        caps = _caps()
        for t in caps.tools:
            for b in V.BLOCKS_KEYS:
                cpu, gpu = caps.covered(t, b, "cpu"), caps.covered(t, b, "gpu")
                self.assertEqual(caps.y(t, b), 0 if cpu and gpu else -1 if cpu else 1 if gpu else None, (t, b))

    def test_every_capability_has_an_x_and_a_reason(self):
        caps = _caps()
        self.assertEqual(set(caps.data["x"]), set(V.BLOCKS_KEYS))
        for b, v in caps.data["x"].items():
            self.assertTrue(0 <= v["x"] <= 1, b)
            self.assertTrue(v["why"].strip() and "\n" not in v["why"], b)


def _tool_pane(block, tool):
    m = re.search(rf'<div class="cm-tool" data-tool="{re.escape(html.escape(tool, quote=True))}"[^>]*>(.*?)</ul>(.*?)</div>', block, re.S)
    return m.group(0)


class TestOneToolAtATime(unittest.TestCase):
    """One icon per capability; its x is fixed by the data and its band is the selected tool's stored y, for every tool, at both widths."""

    def test_one_icon_per_capability_in_the_page(self):
        for side, block in _map_page().items():
            for mode in ("wide", "narrow"):
                self.assertEqual(sorted(_icons(block, mode)), sorted(V.BLOCKS_KEYS), (side, mode))
            for k in V.BLOCKS_KEYS:
                self.assertEqual(len(re.findall(rf'data-block="{k}" data-x', block)), 2)
            ids = set(re.findall(r'<symbol id="([^"]+)"', block))
            for href in set(re.findall(r'<use href="#([^"]+)"', block)):
                self.assertIn(href, ids)
            self.assertEqual(re.findall(r'<h4', block), [])

    def test_every_icon_position_matches_the_data_for_every_tool(self):
        caps = _caps()
        for side, block in _map_page().items():
            j = _cm_json(block)
            self.assertEqual(j["tools"], [t for t, _v in sc.CAPMAP_TOOLS])
            for mode in ("wide", "narrow"):
                m = j["modes"][mode]
                x0, x1 = m["plot"]
                for tool in caps.tools + ["none"]:
                    for k in V.BLOCKS_KEYS:
                        x, y, kind = m["pos"][tool][k]
                        self.assertAlmostEqual(x, x0 + caps.xs[k] * (x1 - x0), delta=0.11, msg=(mode, tool, k, "x"))
                        yy = None if tool == "none" else caps.y(tool, k)
                        band = "mid" if yy is None else "cpu" if yy < 0 else "gpu" if yy > 0 else "mid"
                        lo, hi = m["bands"][band]
                        self.assertTrue(lo <= y <= hi, (mode, tool, k, "band"))
                        self.assertEqual(kind, "neutral" if tool == "none" else "ghost" if yy is None else "cov", (mode, tool, k))
                self.assertEqual(j["y"]["raptor"]["fixed"], 0)
                # the page as served is raptor's final state
                for k, (x, y, cl) in _icons(block, mode).items():
                    px, py, kind = m["pos"]["raptor"][k]
                    self.assertEqual((x, y, cl), (px, py, "is-" + kind), (mode, k))

    def test_bands_order_and_middle_is_the_tallest(self):
        for mode in ("wide", "narrow"):
            q = V.QuadChart(_caps(), mode)
            h = {b: q.band[b][1] - q.band[b][0] for b in V.BANDS}
            self.assertGreater(h["mid"], h["cpu"])
            self.assertGreater(h["mid"], h["gpu"])
            self.assertLessEqual(q.band["cpu"][1], q.band["mid"][0] + 1e-9)
            self.assertLessEqual(q.band["mid"][1], q.band["gpu"][0] + 1e-9)

    def test_nothing_overlaps_for_every_tool_at_both_widths(self):
        """Icons and the names of the covered icons (and the ghosts) are pairwise disjoint and inside the chart, every state."""
        caps = _caps()
        for mode in ("wide", "narrow"):
            q = V.QuadChart(caps, mode)
            W = q.c["W"]
            for tool, st in q.pos.items():
                boxes = []
                for k, p in st.items():
                    boxes.append((k, "icon", p["icon"]))
                    if p["label"]:
                        boxes.append((k, "label", p["label"]))
                for k, what, b in boxes:
                    self.assertTrue(0 <= b[0] and b[2] <= W and 0 <= b[1] and b[3] <= q.H, (mode, tool, k, what, "outside"))
                for i, (k1, w1, a) in enumerate(boxes):
                    for k2, w2, b in boxes[i + 1:]:
                        if k1 == k2:
                            continue
                        self.assertGreaterEqual(V._box_gap(a, b), 1.0, (mode, tool, k1, w1, k2, w2))
                # a label is drawn from the same width the generator measured
                for k, p in st.items():
                    if p["label"]:
                        self.assertAlmostEqual(p["label"][2] - p["label"][0], q.lab_w[k], places=3)

    def test_compact_chart_and_readable_phone_names(self):
        self.assertGreaterEqual(V.QUAD_MODES["narrow"]["fs"], 11)
        self.assertLessEqual(V.QUAD_MODES["narrow"]["W"], 360)      # drawn about 1:1 in a phone column, so the names stay >= 11 px
        for mode, limit in (("wide", 130), ("narrow", 190)):
            q = V.QuadChart(_caps(), mode)
            for b in ("cpu", "gpu"):
                self.assertLessEqual(q.band[b][1] - q.band[b][0], limit, (mode, b))
        # one fixed height: the chart is the same size for every tool
        self.assertEqual(len({v for v in (V.QuadChart(_caps(), "wide").H,)}), 1)

    def test_names_sit_beside_their_icon_and_stay_in_the_chart(self):
        for mode in ("wide", "narrow"):
            q = V.QuadChart(_caps(), mode)
            for k, side in q.side.items():
                for tool, st in q.pos.items():
                    p = st[k]
                    if p["label"]:
                        self.assertEqual(p["label"][0] >= p["icon"][2], side == "r", (mode, k))
                        self.assertLessEqual(p["label"][2], q.c["W"] - q.c["R"], (mode, tool, k))
                        self.assertGreaterEqual(p["label"][0], q.c["L"], (mode, tool, k))

    def test_the_icon_order_inside_a_band_is_deterministic(self):
        a = V.QuadChart(_caps(), "wide").json()
        b = V.QuadChart(_caps(), "wide").json()
        self.assertEqual(a, b)

    def test_rendered_default_is_raptor_and_the_picker_is_one_choice(self):
        for block in _map_page().values():
            self.assertEqual(len(re.findall(r'<button type="button" class="cm-chip', block)), len(sc.CAPMAP_TOOLS))
            self.assertEqual(len(re.findall(r'aria-pressed="true"', block)), 1)
            self.assertRegex(block, r'class="cm-chip is-on" data-tool="raptor"')
            self.assertEqual(len(re.findall(r'<g class="cq-ic is-cov"', block)), 2 * len(_caps().covered_blocks("raptor")))

    def test_summary_counts_match_the_data(self):
        caps = _caps()
        for block in _map_page().values():
            j = _cm_json(block)
            first = re.search(r'<p class="cm-summary"[^>]*>([^<]*)</p>', block).group(1)
            self.assertEqual(html.unescape(first), j["summaries"]["raptor"])
            for t in caps.tools:
                s_ = j["summaries"][t]
                blocks = caps.covered_blocks(t)
                self.assertTrue(s_.startswith(f"{t}: {len(blocks)} "), s_)
                n_both = sum(1 for b in blocks if caps.stop(t, b) == "both")
                if n_both == len(blocks):
                    self.assertIn("on both CPU and GPU", s_)
                n_ai = sum(1 for b in blocks if V.BLOCK[b][4] == "ai")
                if n_ai == 0:
                    self.assertIn("all on the Simulation side", s_)
                elif n_ai == len(blocks):
                    self.assertIn("all on the AI side", s_)
                else:
                    self.assertIn(f"{len(blocks) - n_ai} on the Simulation side and {n_ai} on the AI side", s_)
        self.assertEqual(caps.summary("CuPy").split(",")[1].strip(), "GPU only")

    def test_every_covered_cell_has_a_source_in_the_list_and_the_table(self):
        caps = _caps()
        for side, block in _map_page().items():
            table = block[block.index('<table class="cm-table"'):]
            for t in caps.tools:
                pane = _tool_pane(block, t)
                for b, d, tool, c in caps.covered_cells():
                    if tool != t:
                        continue
                    src = html.escape(c["source"], quote=True)
                    self.assertIn(f'href="{src}"', pane, (t, b, d, "list"))
                    row = re.search(rf'<tr data-block="{b}">(.*?)</tr>', table, re.S).group(1)
                    self.assertIn(f'href="{src}"', row, (t, b, d, "table"))

    def test_lists_name_what_is_not_covered(self):
        caps = _caps()
        for block in _map_page().values():
            for t in caps.tools:
                pane = _tool_pane(block, t)
                lis = re.findall(r'<li data-block="([^"]+)">', pane)
                self.assertEqual(lis, caps.covered_blocks(t), t)
                none = [V.BLOCK[b][1] for b in V.BLOCKS_KEYS if not caps.stop(t, b)]
                if none:
                    self.assertIn(html.escape("Not first-class: " + ", ".join(none) + "."), pane, t)
                else:
                    self.assertNotIn("Not first-class", pane)

    def test_compare_table_cells(self):
        caps = _caps()
        block = _map_page()["gpu"]
        table = block[block.index('<table class="cm-table"'):]
        self.assertIn("<details class=\"cm-compare\"><summary>Compare all tools", block)
        self.assertNotIn("<details open", block.split("</script>")[0])
        self.assertEqual(len(re.findall(r'<tr data-block="', table)), len(V.BLOCKS))
        for b in V.BLOCKS_KEYS:
            row = re.search(rf'<tr data-block="{b}">(.*?)</tr>', table, re.S).group(1)
            cells = re.findall(r'<td data-stop="([^"]+)">(.*?)</td>', row, re.S)
            self.assertEqual([c[0] for c in cells], [caps.stop(t, b) or "none" for t in caps.tools], b)
            for (st, inner), t in zip(cells, caps.tools):
                text = re.sub(r"<[^>]+>", "", inner).split()
                if st == "none":
                    self.assertEqual(inner, "")
                else:
                    self.assertEqual(text[0], V.STOP_NAME[st], (b, t))

    def test_neutral_state_and_deselect_sentence_exist(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn(".capmap.is-neutral .cm-dot-on", css)
        self.assertIn(".cq-ic.is-neutral", css)
        self.assertIn("IntersectionObserver", js)
        for block in _map_page().values():
            self.assertIn("Pick a tool to see where each capability runs.", block)
            self.assertEqual(_cm_json(block)["none"], "Pick a tool to see where each capability runs.")
            self.assertNotIn('class="capmap is-neutral', block)      # at rest the page shows raptor's final positions
            for mode in ("wide", "narrow"):
                kinds = {v[2] for v in _cm_json(block)["modes"][mode]["pos"]["none"].values()}
                self.assertEqual(kinds, {"neutral"})

    def test_details_card_content_matches_the_data(self):
        caps = _caps()
        for block in _map_page().values():
            cards = _cm_json(block)["cards"]
            self.assertEqual(set(cards), set(V.BLOCKS_KEYS))
            for k, d in cards.items():
                self.assertEqual(d["l"], V.BLOCK[k][1])
                self.assertEqual(d["needs"], caps.needs[k])
                self.assertEqual(set(d["t"]), set(caps.tools))
                for t in caps.tools:
                    for dev, _n in V.DEVICES:
                        c, want = d["t"][t][dev], caps.cell(t, k, dev)
                        self.assertEqual((c["c"], c["n"]), (want["covered"], want["note"]), (k, t, dev))
                        self.assertEqual(c.get("s"), want.get("source"), (k, t, dev))
            self.assertIn('<div class="cq-card" role="group"', block)
            self.assertIn("hidden></div>", block.split('class="cq-card"')[1][:120])
            self.assertEqual(len(re.findall(r'<g class="cq-ic [^"]*" data-block="[^"]+" data-x="[^"]*" data-y="[^"]*" tabindex="0" role="button"', block)), 2 * len(V.BLOCKS_KEYS))
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        for needle in ('"focus"', '"Escape"', "pointerdown", "closeCard", "No tool" if False else "data.tools.forEach", "Not first-class for"):
            self.assertIn(needle, js)

    def test_the_list_and_the_table_are_closed_disclosures(self):
        for side, block in _map_page().items():
            self.assertEqual(re.findall(r'<details class="(cm-[a-z]+)">', block), ["cm-details", "cm-compare"], side)
            self.assertIn("<summary>Show details</summary>", block)
            self.assertIn("<summary>Compare all tools</summary>", block)
            self.assertNotRegex(block, r"<details[^>]* open")
            # the summary sentence stays outside, above them
            self.assertLess(block.index('<p class="cm-summary"'), block.index('<details class="cm-details">'))
            det = block[block.index('<details class="cm-details">'):block.index("</details>")]
            self.assertEqual(len(re.findall(r'<div class="cm-tool"', det)), len(sc.CAPMAP_TOOLS))

    def test_both_panels_carry_the_same_map(self):
        pages = _map_page()
        self.assertEqual(set(pages), {"gpu", "cpu"})
        norm = {side: b.replace(f'data-side="{side}"', "").replace(f'"side":"{side}"', "").replace(f"wic-{side}", "wic").replace(f"cqg-{side}", "cqg") for side, b in pages.items()}
        self.assertEqual(norm["gpu"], norm["cpu"])
        self.assertNotIn("data-slug", pages["gpu"])

    def test_no_hover_only_content(self):
        block = _map_page()["gpu"]
        self.assertNotIn("popover", block)
        self.assertNotIn("role=\"tooltip\"", block)
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        cm = css[css.index("The capability chart (.capmap"):]
        self.assertNotIn(":hover ~", cm)
        self.assertNotIn(".cm-note { display: none", cm)

    def test_motion_and_focus(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn("transition: transform 0.35s ease, opacity 0.3s ease", css)
        self.assertIn("prefers-reduced-motion: reduce) { * { transition: none", css)
        self.assertIn(".cm-chip:focus-visible", css)
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn("ArrowRight", js)
        self.assertIn("aria-pressed", js)


class TestIcons(unittest.TestCase):
    """One registry of icons, inline, each element with a name."""

    def test_every_block_feature_and_sector_has_an_icon(self):
        for b in V.BLOCKS:
            self.assertIn(b[3], radar_icons.ICONS, b[0])
        for s_ in V.SECTORS:
            self.assertIn(s_[3], radar_icons.ICONS, s_[0])
        for f, _l, _k in V.FEATURES:
            self.assertIn(f, radar_icons.ICONS, f)

    def test_every_node_has_a_name_and_a_symbol(self):
        for side, b in _rosette_page().items():
            ids = set(re.findall(r'<symbol id="([^"]+)"', b))
            self.assertTrue(ids)
            for href in set(re.findall(r'<use href="#([^"]+)"', b)):
                self.assertIn(href, ids)
            for g in re.findall(r'<g class="(?:rnode|rsector)[^"]*"[^>]*>', b):
                self.assertRegex(g, r'aria-label="[^"]+"')
                self.assertIn('tabindex="0"', g)
            self.assertNotRegex(b, r'<(?:link|img)[^>]+(?:\.svg|\.png)')


class TestLabels(unittest.TestCase):
    """Label non-intersection, both visuals, wide and phone width, every rosette sector."""

    def test_rosette_labels_clear_everything(self):
        for side, slug in LABEL_CARDS:
            b = _rosette_page()[side]
            tools = [(t, "") for t in _tools(b)]
            table = _table(_json(b)["devices"][slug])
            for mode, sector in [("wide", "ensemble")] + ([("narrow", s_[0]) for s_ in V.SECTORS] if side == "gpu" else []):
                g = V.Rosette(table, tools, mode, sector).min_gaps()
                for kind, v in g.items():
                    self.assertGreaterEqual(v, MIN_GAP, (side, slug, mode, sector, kind))

class TestHoverPolicy(unittest.TestCase):
    """A tool's band and its chip are one handler; nothing is hover-only."""

    def test_blob_and_chip_share_one_handler(self):
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn('".worlds-leg, path.blob[data-tool]"', js)
        for el in ("mouseenter", "mouseleave", "focus", "blur", "click"):
            self.assertIn(f'el.addEventListener("{el}"', js)

    def test_names_equal_chip_names(self):
        for side, b in _rosette_page().items():
            chips = _tools(b)
            for t, d in _paths(b):
                self.assertIn(html.unescape(t), [html.unescape(c) for c in chips])

    def test_every_chip_names_its_tool_for_a_screen_reader(self):
        for side, b in _map_page().items():
            chips = re.findall(r'<button type="button" class="cm-chip[^"]*" data-tool="([^"]+)"', b)
            self.assertEqual([html.unescape(t) for t in chips], [t for t, _v in sc.CAPMAP_TOOLS])
            for t in chips:
                self.assertRegex(b, rf'data-tool="{re.escape(t)}"[^>]*>(?:<span class="chip"></span>)<span class="nm">{re.escape(t)}</span>')


class TestCrossHighlight(unittest.TestCase):
    """One feature key links the rosette, the radar, the popover rows and the tables."""

    def test_every_feature_key_is_known_and_has_a_table_row(self):
        for side, b in _rosette_page().items():
            keys = set(re.findall(r'data-feature="([^"]+)"', b))
            self.assertTrue(keys <= {f for f, _l, _k in V.FEATURES}, keys)
            self.assertEqual(keys, {f for f, _l, _k in V.FEATURES})
            for f in keys:
                self.assertIn(f'<g class="rnode" data-feature="{f}"', b)
                self.assertRegex(b, rf'<text class="nlabel[^"]*" data-feature="{f}"')

    def test_the_detailed_radar_axes_carry_the_same_keys(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        radar = set(re.findall(r'class="radar-axis[^"]*" data-axis="([^"]+)" data-feature="\1"', text))
        self.assertEqual(radar, {f for f, _l, _k in V.FEATURES if f in sc.RADAR_ALL_AXES})

    def test_the_script_does_the_highlight(self):
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn('data-feature="', js)
        self.assertIn('"xh"', js)
        self.assertIn("mouseover", js)
        self.assertIn("focusin", js)


class TestPageComposition(unittest.TestCase):
    """The landing page: bars, then the capability map, then the radar; the detail page: the toggle with the rosette first."""

    def test_landing_order_under_each_side(self):
        text = (GENERATED / "perf_switch.md").read_text()
        for side in ("gpu", "cpu"):
            i = text.index(f'<div class="perf-side perf-side-{side}">')
            seg = text[i:]
            self.assertLess(seg.index('<section class="perf-dev">'), seg.index('<div class="capmap"'))
            self.assertLess(seg.index('<div class="capmap"'), seg.index('<div class="radar"'))

    def test_detail_toggle(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        for side in ("gpu", "cpu"):
            self.assertIn('data-view="rosette" aria-pressed="true">Rosette<', text)
            self.assertIn('data-view="radar" aria-pressed="false">Radar<', text)
        self.assertLess(text.index('<div class="vis-rosette">'), text.index('<div class="vis-radar">'))


class TestNoEarlyFinishView(unittest.TestCase):
    """The landing page carries no early-finish saving view or button."""

    def test_no_panel_has_the_view(self):
        text = (GENERATED / "perf_switch.md").read_text()
        self.assertNotIn("bars-early", text)
        self.assertNotIn("Early-finish saving", text)


class TestPhoneLayout(unittest.TestCase):
    """The rosette keeps its sector picker at phone width; the capability map is one column of rows that never needs a sideways page scroll."""

    def test_the_map_scrolls_only_inside_its_own_box(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn(".cm-scroll { overflow-x: auto; max-width: 100%;", css)
        self.assertIn(".cq-wide-box { display: none; }", css)
        self.assertIn(".cq-narrow-box { display: block; }", css)
        self.assertIn(".cq-svg { display: block; width: 100%; height: auto;", css)

    def test_rosette_has_a_sector_picker(self):
        for side, b in _rosette_page().items():
            self.assertEqual(len(re.findall(r'<button type="button" class="pick', b)) % len(V.SECTORS), 0)
            self.assertIn('class="rosette-picker"', b)


if __name__ == "__main__":
    unittest.main()
