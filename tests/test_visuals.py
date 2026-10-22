# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The capability chart and its data. The chart is static and sourced: what it shows for every tool (each icon's place, the
sentence, the list, the table, the card) is compared with ``_data/capabilities.json``; the judged radar axes are held to the
same sourced capability rows."""
import functools
import html
import json
import pathlib
import re
import sys
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_cards as sc  # noqa: E402
import visuals as V  # noqa: E402

GENERATED = SITE_ROOT / "_generated"


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
def _caps():
    return V.Capabilities(json.loads((SITE_ROOT / "_data" / "capabilities.json").read_text()))


class TestCapabilityData(unittest.TestCase):
    """The map's coverage is static and sourced: every cell is in the data file, and every covered one has a source."""

    def test_every_cell_is_present_and_every_covered_cell_has_a_source(self):
        caps = _caps()
        self.assertEqual(caps.tools, [t for t, _v in sc.CAPMAP_TOOLS])
        self.assertEqual(set(caps.needs), set(V.BLOCKS_KEYS))
        for t in caps.tools:
            self.assertEqual(set(caps.cells[t]), set(V.BLOCKS_KEYS), t)
            for b in V.BLOCKS_KEYS:
                self.assertEqual(set(caps.cells[t][b]), {d for d, _n in V.DEVICES} | {"y", "g"}, (t, b))
                for d, _n in V.DEVICES:
                    c = caps.cell(t, b, d)
                    self.assertIsInstance(c["covered"], bool, (t, b, d))
                    if c["covered"]:
                        self.assertRegex(c["source"], r"^https://[^\s\"<>]+$", (t, b, d))
                        self.assertTrue(c["note"].strip(), (t, b, d))
                        self.assertNotIn("\n", c["note"])
                    else:
                        self.assertNotIn("source", c, (t, b, d))

    def test_grades_are_sourced_and_agree_with_coverage(self):
        """g is 0-5 or null (no confirming source, shown blank); a graded cell has a reason and a source; covered means 3 or
        more and not covered 2 or less."""
        caps = _caps()
        for t in caps.tools:
            for b in V.BLOCKS_KEYS:
                g = caps.grade(t, b)
                if g is None:
                    continue
                self.assertEqual(set(g), {"g", "reason", "source", "kind"}, (t, b))
                self.assertIn(g["g"], range(6), (t, b))
                self.assertTrue(g["reason"].strip() and "\n" not in g["reason"], (t, b))
                self.assertRegex(g["source"], r"^(https://[^\s\"<>]+|repo: \S.*)$", (t, b))
                self.assertIn(g["kind"], ("doc", "scope", "repo"), (t, b))
                if t != "raptor":
                    self.assertRegex(g["source"], r"^https://", (t, b))
                if g["kind"] == "scope":
                    self.assertEqual(g["g"], 0, (t, b))
                covered = bool(caps.stop(t, b))
                self.assertEqual(g["g"] >= 3, covered, (t, b, g["g"]))

    def test_the_grade_is_on_the_map_for_every_tool(self):
        caps = _caps()
        for block in _map_page().values():
            cards = _cm_json(block)["cards"]
            for k in V.BLOCKS_KEYS:
                for t in caps.tools:
                    g, want = cards[k]["t"][t]["g"], caps.grade(t, k)
                    self.assertEqual(g and (g["v"], g["r"], g["s"]), want and (want["g"], want["reason"], want["source"]), (k, t))
            for k in V.BLOCKS_KEYS:     # the default tool's grade is in the page's own markup, blank when null
                want = caps.grade("raptor", k)
                for mode in ("wide", "narrow"):
                    svg = re.search(rf'<svg class="cq-svg cq-{mode}".*?</svg>', block, re.S).group(0)
                    ic = re.search(rf'<g class="cq-ic [^"]*" data-block="{k}"[^>]*? data-g="(\d?)"', svg)
                    self.assertEqual(ic.group(1), "" if want is None else str(want["g"]), (k, mode))
            self.assertIn("cm-g", block)

    def test_the_measured_rule_is_gone_from_the_map(self):
        block = _map_page()["gpu"]
        self.assertNotIn("2×", block)
        self.assertNotIn("of 5", block)
        self.assertIn("speed is in the bars and the radar", block)

    def test_the_rulings_hold(self):
        caps = _caps()
        for b in ("divergent", "events"):
            self.assertIsNone(caps.stop("Numba", b), b)
        self.assertEqual(caps.stop("NVIDIA Warp", "deploy"), "both")
        self.assertEqual(caps.stop("CuPy", "handtuned"), "gpu")
        self.assertEqual(caps.stop("CuPy", "half"), "gpu")
        self.assertNotIn("float8", caps.cell("JAX", "half", "gpu")["note"] + caps.cell("JAX", "inference", "gpu")["note"])
        for t in caps.tools:
            for b in V.BLOCKS_KEYS:
                for d, _n in V.DEVICES:
                    self.assertNotIn(caps.cell(t, b, d)["note"], ("CuPy runs on GPUs.", "NumPy runs on the CPU."))

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


class TestJudgedAxesAgreeWithCapabilities(unittest.TestCase):
    """The judged radar scores and the sourced capability rows tell one story: a score of 4 or more needs the capability
    covered (on at least one device), and a covered capability must not score 2 or less."""

    def _axes(self):
        return json.loads((SITE_ROOT / "_data" / "radar_qualitative.json").read_text())["axes"]

    def test_every_judged_axis_is_mapped_with_a_reason(self):
        caps, axes = _caps(), self._axes()
        mapping = caps.data["radar_axes"]["map"]
        self.assertEqual(set(mapping), set(axes))
        for ax, m in mapping.items():
            self.assertTrue(m["why"].strip() and "\n" not in m["why"], ax)
            self.assertTrue(set(m["blocks"]) <= set(V.BLOCKS_KEYS), ax)
        self.assertTrue(any(m["blocks"] for m in mapping.values()))

    def test_scores_and_coverage_agree(self):
        caps, axes = _caps(), self._axes()
        for ax, m in caps.data["radar_axes"]["map"].items():
            if not m["blocks"]:
                continue
            for tool, v in axes[ax]["scores"].items():
                covered = any(caps.stop(tool, b) for b in m["blocks"])
                if v["score"] >= 4:
                    self.assertTrue(covered, f"{tool} scores {v['score']} on {ax} but covers none of {m['blocks']}")
                if covered:
                    self.assertGreater(v["score"], 2, f"{tool} covers {m['blocks']} but scores {v['score']} on {ax}")


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
                    self.assertEqual(re.sub(r"<[^>]+>", "", inner), str(caps.grade(t, b)["g"]) if caps.grade(t, b) else "")
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
    """The chart's icons come from the shared registry, inline, each element with a name."""

    def test_every_block_has_an_icon(self):
        import radar_icons
        for b in V.BLOCKS:
            self.assertIn(b[3], radar_icons.ICONS, b[0])

    def test_no_external_images(self):
        for b in _map_page().values():
            self.assertNotRegex(b, r'<(?:link|img)[^>]+(?:\.svg|\.png)')


class TestHoverPolicy(unittest.TestCase):
    """The tool chips name their tool for a screen reader; nothing is hover-only."""

    def test_every_chip_names_its_tool(self):
        for side, b in _map_page().items():
            chips = re.findall(r'<button type="button" class="cm-chip[^"]*" data-tool="([^"]+)"', b)
            self.assertEqual([html.unescape(t) for t in chips], [t for t, _v in sc.CAPMAP_TOOLS])
            for t in chips:
                self.assertRegex(b, rf'data-tool="{re.escape(t)}"[^>]*>(?:<span class="chip"></span>)<span class="nm">{re.escape(t)}</span>')


class TestCrossHighlight(unittest.TestCase):
    """One feature key links a radar axis and its table rows."""

    def test_the_detailed_radar_axes_carry_feature_keys(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        radar = set(re.findall(r'class="radar-axis[^"]*" data-axis="([^"]+)" data-feature="\1"', text))
        self.assertEqual(radar, {k for k in sc.RADAR_ALL_AXES if k in sc.RADAR_MODE_KEYS["detailed"]})

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

    def test_detail_page_carries_the_radar_only(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        self.assertNotIn("rosette", text.lower())
        self.assertNotIn("view-toggle", text)
        self.assertIn('<div class="radar radar-detailed" data-side="gpu" data-mode="detailed">', text)


class TestNoEarlyFinishView(unittest.TestCase):
    """The landing page carries no early-finish saving view or button."""

    def test_no_panel_has_the_view(self):
        text = (GENERATED / "perf_switch.md").read_text()
        self.assertNotIn("bars-early", text)
        self.assertNotIn("Early-finish saving", text)


class TestPhoneLayout(unittest.TestCase):
    """The chart picks its layout by the width of its own container, not the viewport; neither layout needs a sideways page scroll."""

    def test_the_layout_follows_the_container_not_the_viewport(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn("container-type: inline-size", css[css.index(".capmap {"):][:300])
        i = css.index("@container (max-width: 699px) {\n  .cq-wide-box { display: none; }")
        self.assertNotIn("@media", css[i - 20:i])
        # in the narrowest container that still gets the wide drawing (700 px) its names are still 11 px or more
        w = V.QUAD_MODES["wide"]
        self.assertGreaterEqual(w["fs"] * 700 / w["W"], 11.0)
        # and the narrow drawing is capped so it never blows up in a middle-width column
        self.assertIn(".cq-narrow-box { max-width: 480px;", css)
        n = V.QUAD_MODES["narrow"]
        self.assertGreaterEqual(n["fs"] * 340 / n["W"], 11.0)
        for block in _map_page().values():
            self.assertIn('class="cq-wide-box"', block)
            self.assertIn('class="cq-narrow-box"', block)

    def test_the_map_scrolls_only_inside_its_own_box(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn(".cm-scroll { overflow-x: auto; max-width: 100%;", css)
        self.assertIn(".cq-wide-box { display: none; }", css)
        self.assertIn(".cq-narrow-box { display: block; }", css)
        self.assertIn(".cq-svg { display: block; width: 100%; height: auto;", css)

if __name__ == "__main__":
    unittest.main()
