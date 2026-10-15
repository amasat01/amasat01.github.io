# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The two coverage visuals (the capability map, the rosette) and their data. The map is static and sourced: its geometry
is rebuilt from ``_data/capabilities.json`` with the same code that drew it and compared with what was drawn; the rosette
is rebuilt from the page's own JSON (coverage verdicts) on every device the generated pages carry."""
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
    return {side: b for side, b in _blocks(text, "worlds capmap")}


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


@functools.lru_cache(maxsize=None)
def _map(mode):
    return V.CapMap(_caps(), list(sc.CAPMAP_TOOLS), V.CAPMAP_LAYOUT[mode])


def _paths(part, cls="blob"):
    return re.findall(rf'<path class="{cls}[^"]*" data-tool="([^"]+)"[^>]*? d="([^"]+)"', part)


def _parts():
    """(wide html, narrow html) of the map as drawn under the GPU panel."""
    b = _map_page()["gpu"]
    return b.split('<div class="worlds-narrow">')[0], b.split('<div class="worlds-narrow">')[1]


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
                self.assertEqual(set(caps.cells[t][b]), {d for d, _n in V.DEVICES}, (t, b))
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
        self.assertIn("Speed is not part of it", block)

    def test_the_table_lists_every_covered_cell_once_with_its_source(self):
        caps = _caps()
        for side, block in _map_page().items():
            rows = re.findall(r'<tr data-block="([^"]+)" data-device="([^"]+)" data-tool="([^"]+)">(.*?)</tr>', block, re.S)
            want = [(b, d, t) for b, d, t, _c in caps.covered_cells()]
            self.assertEqual([(b, d, html.unescape(t)) for b, d, t, _r in rows], want, side)
            for (b, d, t, row), (_b, _d, _t, c) in zip(rows, caps.covered_cells()):
                self.assertIn(f'<a href="{html.escape(c["source"], quote=True)}">source</a>', row)
                self.assertIn(html.escape(c["note"]), row)

    def test_table_cell_count_equals_the_map_coverage(self):
        wide_html, narrow_html = _parts()
        drawn = len(re.findall(r'<path class="arc" data-tool=', wide_html))
        rows = len(re.findall(r'<tr data-block="[^"]+" data-device=', _map_page()["gpu"]))
        cov = sum(len(_map("wide").cov[t]) for t in _map("wide").tools)
        self.assertEqual(rows, cov)
        self.assertEqual(drawn, cov)
        self.assertEqual(len(re.findall(r'<path class="arc" data-tool=', narrow_html.split("</svg>")[0])), cov)

    def test_popover_json_mirrors_the_data(self):
        caps = _caps()
        for side, block in _map_page().items():
            j = _json(block)
            self.assertEqual(j["side"], side)
            for nid, n in j["map"]["nodes"].items():
                d, b = V.split_node(nid)
                self.assertEqual([w[0] for w in n["w"]], caps.who(b, d))
                for t, note, src in n["w"]:
                    self.assertEqual((note, src), (caps.cell(t, b, d)["note"], caps.cell(t, b, d)["source"]))
            self.assertEqual(set(j["map"]["nodes"]), set(caps.nodes()))


class TestOneMap(unittest.TestCase):
    """The map is the same on every device: no device switch, no per-card variant."""

    def test_both_panels_carry_the_same_map(self):
        pages = _map_page()
        self.assertEqual(set(pages), {"gpu", "cpu"})
        norm = {side: b.replace(f'data-side="{side}"', "").replace(f"wic-{side}", "wic").replace(f'"side":"{side}"', "")
                .replace(f"-{side}w", "-w").replace(f"-{side}n", "-n") for side, b in pages.items()}
        self.assertEqual(norm["gpu"], norm["cpu"])
        self.assertNotIn("data-slug", pages["gpu"])
        self.assertNotIn("worlds-dev", pages["gpu"])

    def test_every_block_appears_on_each_row_where_a_tool_does_it(self):
        caps = _caps()
        for d, _n in V.DEVICES:
            for b in V.BLOCKS_KEYS:
                self.assertEqual(V.node_id(d, b) in caps.nodes(), bool(caps.who(b, d)), (d, b))
        for mode in ("wide", "narrow"):
            lay = V.CAPMAP_LAYOUT[mode]
            for nid in caps.nodes():
                d, b = V.split_node(nid)
                x, y = lay["pos"][nid]
                self.assertEqual(y < lay["rows"], d == "cpu", (mode, nid, "row"))
                self.assertEqual(x > lay["cols"], V.BLOCK[b][4] == "ai", (mode, nid, "column"))


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
        for side, b in list(_map_page().items()) + list(_rosette_page().items()):
            ids = set(re.findall(r'<symbol id="([^"]+)"', b))
            self.assertTrue(ids)
            for href in set(re.findall(r'<use href="#([^"]+)"', b)):
                self.assertIn(href, ids)
            for g in re.findall(r'<g class="(?:wnode|rnode|rsector)[^"]*"[^>]*>', b):
                self.assertRegex(g, r'aria-label="[^"]+"')
                self.assertIn('tabindex="0"', g)
            self.assertNotRegex(b, r'<(?:link|img)[^>]+(?:\.svg|\.png)')


class TestConvexityAndClearance(unittest.TestCase):
    """Every drawn blob is the rounded convex hull of its covered blocks, and every uncovered block clears it."""

    def test_drawn_shapes_are_the_hulls(self):
        for mode, part in zip(("wide", "narrow"), _parts()):
            w = _map(mode)
            want = [(t, blob.path()) for t in w.tools for blob, _m in w.pieces[t]]
            self.assertEqual([(html.unescape(t), d) for t, d in _paths(part)], want, mode)
            for t in w.tools:
                for blob, members in w.pieces[t]:
                    self.assertEqual(sorted(blob.hull), sorted(V.convex_hull([w.pos[k] for k in members])))
                    c = blob.core
                    if len(c) >= 3:
                        signs = {math.copysign(1, (c[(i + 1) % len(c)][0] - c[i][0]) * (c[(i + 2) % len(c)][1] - c[(i + 1) % len(c)][1])
                                               - (c[(i + 1) % len(c)][1] - c[i][1]) * (c[(i + 2) % len(c)][0] - c[(i + 1) % len(c)][0])) for i in range(len(c))}
                        self.assertEqual(len(signs), 1, (mode, t, "core is not convex"))

    def test_uncovered_blocks_clear_every_outline(self):
        for mode in ("wide", "narrow"):
            w = _map(mode)
            self.assertEqual(w.violations, [], mode)
            for t in w.tools:
                for blob, members in w.pieces[t]:
                    for k in w.nodes:
                        d = blob.distance(w.pos[k])
                        if k in members:
                            self.assertLessEqual(d, -(w.node + V.CLEAR), (mode, t, k, "not enclosed"))
                        elif k not in w.cov[t]:
                            self.assertGreaterEqual(d, w.node + V.CLEAR, (mode, t, k, "enclosed or too close"))
        self.assertEqual(V.NODE_R + V.CLEAR, 23)

    def test_drawn_arcs_bulge_outwards(self):
        """The drawn SVG outline, not only the geometry: the midpoint of every arc in a blob's path lies on that blob's
        outline. An arc swept the wrong way (an inward cap) puts it deep inside and leaves blocks outside."""
        def arc_mid(p, q, r, large, sweep):
            # SVG arc centre parameterisation (SVG 1.1 F.6.5), circle case
            mx, my = (p[0] - q[0]) / 2, (p[1] - q[1]) / 2
            h2 = max(r * r - mx * mx - my * my, 0.0)
            k = math.sqrt(h2 / (mx * mx + my * my)) * (-1 if large == sweep else 1)
            cx, cy = k * my + (p[0] + q[0]) / 2, -k * mx + (p[1] + q[1]) / 2
            a0 = math.atan2(p[1] - cy, p[0] - cx)
            d = (math.atan2(q[1] - cy, q[0] - cx) - a0) % (2 * math.pi)
            if not sweep:
                d -= 2 * math.pi
            return cx + r * math.cos(a0 + d / 2), cy + r * math.sin(a0 + d / 2)

        tok = re.compile(r"([MLAZ])([^MLAZ]*)")
        for mode in ("wide", "narrow"):
            w = _map(mode)
            for t in w.tools:
                for blob, _m in w.pieces[t]:
                    cur = None
                    for cmd, args in tok.findall(blob.path()):
                        v = [float(x) for x in args.split()]
                        if cmd in "ML":
                            cur = (v[0], v[1])
                        elif cmd == "A":
                            nxt = (v[5], v[6])
                            mid = arc_mid(cur, nxt, v[0], int(v[3]), int(v[4]))
                            self.assertLess(abs(blob.distance(mid)), 1.0, (mode, t, "arc swept inwards"))
                            cur = nxt

    def test_path_snapshot(self):
        """Two-decimal coordinates and a per-corner sweep (a mirror-image arc would be a different string)."""
        self.assertEqual(V.rounded_hull_path([(0, 0), (100, 0), (0, 100)], 10),
                         "M0.00 -10.00L100.00 -10.00A10.00 10.00 0 0 1 107.07 7.07L7.07 107.07A10.00 10.00 0 0 1 -10.00 100.00"
                         "L-10.00 0.00A10.00 10.00 0 0 1 0.00 -10.00Z")

    def test_raptor_is_never_split(self):
        for mode in ("wide", "narrow"):
            self.assertEqual(len(_map(mode).pieces["raptor"]), 1)
            self.assertNotIn("raptor", V.FALLBACK)

    def test_the_fallback_cases_are_named(self):
        """Pieces beyond one hull are the ruled fallback, allowed only for the tools `V.FALLBACK` names; today none needs it,
        so a change that adds one is a visible edit here."""
        self.assertEqual(V.FALLBACK, {})
        for mode in ("wide", "narrow"):
            w = _map(mode)
            self.assertEqual(w.split, [], mode)
            for t in w.tools:
                self.assertEqual(len(w.pieces[t]), 1 if w.cov[t] else 0, (mode, t))


class TestLabels(unittest.TestCase):
    """Label non-intersection, both visuals, wide and phone width, every rosette sector."""

    def test_map_labels_clear_everything(self):
        w = _map("wide")
        self.assertGreaterEqual(min(v["gap"] for v in w.labels.values()), MIN_GAP)
        for k, tt in w.titles().items():
            self.assertGreaterEqual(tt["gap"], MIN_GAP, k)
        for t, nb in w.name_boxes().items():
            self.assertGreaterEqual(nb["gap"], MIN_GAP, ("name", t))
        boxes = [v["box"][:4] for v in w.labels.values()]
        circles, pts = w._obstacles()
        width, height = w.lay["size"]
        for i, a in enumerate(boxes):
            self.assertTrue(0 <= a[0] and a[2] <= width and 0 <= a[1] and a[3] <= height, a)
            for b in boxes[i + 1:]:
                self.assertGreaterEqual(V._box_gap(a, b), MIN_GAP)
            for c, r in circles:
                self.assertGreaterEqual(V._box_node_gap(a, c, r), MIN_GAP)
            self.assertGreaterEqual(min(V._gap(a, p) for p in pts), MIN_GAP)
        for k, tt in _map("narrow").titles().items():
            self.assertGreaterEqual(tt["gap"], MIN_GAP, (k, "narrow"))

    def test_rosette_labels_clear_everything(self):
        for side, slug in LABEL_CARDS:
            b = _rosette_page()[side]
            tools = [(t, "") for t in _tools(b)]
            table = _table(_json(b)["devices"][slug])
            for mode, sector in [("wide", "ensemble")] + ([("narrow", s_[0]) for s_ in V.SECTORS] if side == "gpu" else []):
                g = V.Rosette(table, tools, mode, sector).min_gaps()
                for kind, v in g.items():
                    self.assertGreaterEqual(v, MIN_GAP, (side, slug, mode, sector, kind))

    def test_nothing_leaves_the_phone_column(self):
        w = _map("narrow")
        width, height = w.lay["size"]
        for t in w.tools:
            for blob, _m in w.pieces[t]:
                xs = [p[0] for p in blob.outline(6)]
                ys = [p[1] for p in blob.outline(6)]
                self.assertGreaterEqual(min(xs), 0, t)
                self.assertLessEqual(max(xs), width, t)
                self.assertGreaterEqual(min(ys), 0, t)
                self.assertLessEqual(max(ys), height, t)
        for k, tt in w.titles().items():
            self.assertGreaterEqual(tt["box"][0], 0)
            self.assertLessEqual(tt["box"][2], width)


class TestHoverPolicy(unittest.TestCase):
    """A tool's blob and its chip are one handler; the drawn name is the chip's name; nothing is hover-only."""

    def test_blob_and_chip_share_one_handler(self):
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn('".worlds-leg, path.blob[data-tool]"', js)
        for el in ("mouseenter", "mouseleave", "focus", "blur", "click"):
            self.assertIn(f'el.addEventListener("{el}"', js)

    def test_names_equal_chip_names(self):
        for side, b in list(_map_page().items()) + list(_rosette_page().items()):
            chips = _tools(b)
            for t, d in _paths(b):
                self.assertIn(html.unescape(t), [html.unescape(c) for c in chips])
            for name in re.findall(r'<text class="bname" data-tool="([^"]+)"[^>]*>([^<]*)</text>', b):
                self.assertEqual(name[0], name[1])
                self.assertIn(name[0], chips)

    def test_every_chip_names_its_tool_for_a_screen_reader(self):
        for side, b in _map_page().items():
            self.assertEqual([html.unescape(t) for t in _tools(b)], [t for t, _v in sc.CAPMAP_TOOLS])
            for t in _tools(b):
                self.assertIn(f'aria-label="{t}"', b)

    def test_the_popover_carries_the_sources(self):
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn('link(w[2], "source")', js)
        self.assertIn("closeSoon", js)          # the popover stays while the pointer moves into it to follow a link


class TestCrossHighlight(unittest.TestCase):
    """One feature key links the rosette, the radar, the popover rows and the tables; one block key links a map block's
    two rows, its key-list entry and its table rows."""

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
        self.assertIn('"block:"', js)

    def test_every_map_block_key_links_its_rows(self):
        caps = _caps()
        b = _map_page()["gpu"]
        for nid in caps.nodes():
            d, k = V.split_node(nid)
            self.assertIn(f'data-node="{nid}" data-block="{k}" data-device="{d}"', b)
            self.assertIn(f'<li data-block="{k}">', b)


class TestPageComposition(unittest.TestCase):
    """The landing page: bars, then the capability map, then the radar; the detail page: the toggle with the rosette first."""

    def test_landing_order_under_each_side(self):
        text = (GENERATED / "perf_switch.md").read_text()
        for side in ("gpu", "cpu"):
            i = text.index(f'<div class="perf-side perf-side-{side}">')
            seg = text[i:]
            self.assertLess(seg.index('<section class="perf-dev">'), seg.index('<div class="worlds capmap"'))
            self.assertLess(seg.index('<div class="worlds capmap"'), seg.index('<div class="radar"'))

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
    """At phone width the icons stand in for the labels, each reachable and named, with the key listed once; CPU over GPU."""

    def test_narrow_charts_have_no_label_text_and_a_key(self):
        _wide, narrow = _parts()
        svg = narrow.split("</svg>")[0]
        self.assertNotIn('class="nlabel', svg)
        self.assertEqual(len(re.findall(r'<li data-block="', narrow)), len(V.BLOCKS))
        self.assertEqual(len(re.findall(r'class="wnode', svg)), len(_caps().nodes()))

    def test_the_legend_is_letters_on_a_phone(self):
        css = (SITE_ROOT / "_static" / "custom.css").read_text()
        self.assertIn(".worlds-leg .nm { display: none; }", css)
        self.assertIn(".worlds-leg .mono { display: inline; }", css)

    def test_rosette_has_a_sector_picker(self):
        for side, b in _rosette_page().items():
            self.assertEqual(len(re.findall(r'<button type="button" class="pick', b)) % len(V.SECTORS), 0)
            self.assertIn('class="rosette-picker"', b)


if __name__ == "__main__":
    unittest.main()
