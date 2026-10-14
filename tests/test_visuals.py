# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The two coverage visuals (two worlds, rosette) and their data: the ten acceptance tests of the design ruling, run on every
device the generated pages carry. Geometry is rebuilt from the page's own JSON (coverage verdicts) with the same code that drew it,
then compared with what was drawn."""
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
#: Label geometry is fixed per side, so label gaps are checked on one card per side.
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
    """[(slug, html of that device)] of a worlds / rosette block."""
    parts = re.split(r'(?=<div class="worlds-dev)', block)[1:]
    return [(re.search(r'data-slug="([^"]+)"', p).group(1), p) for p in parts]


@functools.lru_cache(maxsize=None)
def _worlds_page():
    text = (GENERATED / "perf_switch.md").read_text()
    return {side: b for side, b in _blocks(text, "worlds")}


@functools.lru_cache(maxsize=None)
def _rosette_page():
    text = (GENERATED / "radar_detailed.md").read_text()
    return {side: b for side, b in _blocks(text, "rosette")}


def _table(dev_json):
    t = {}
    for f, per_tool in dev_json["vals"].items():
        t[f] = {tool: {"ok": bool(v[2])} for tool, v in per_tool.items() if v is not None}
    return t


@functools.lru_cache(maxsize=None)
def _worlds(side, slug, mode):
    block = _worlds_page()[side]
    tools = [(t, "") for t in _tools(block)]
    table = _table(_json(block)["devices"][slug])
    if mode == "wide":
        lay = V.WORLDS_LAYOUT["wide" if side == "gpu" else "wide_cpu"]
    else:
        lay = V.narrow_layout(side, **{k: V.NARROW[k] for k in ("sx", "sy", "node", "icon", "pad_scale", "size")})
    return V.Worlds(table, tools, lay)


def _all_devices():
    return [(side, slug) for side, b in _worlds_page().items() for slug in _json(b)["devices"]]


def _paths(dev_html, cls="blob"):
    return re.findall(rf'<path class="{cls}[^"]*" data-tool="([^"]+)"[^>]*? d="([^"]+)"', dev_html)


class TestCoverageRule(unittest.TestCase):
    """1. The verdict on every feature is the radar's rule, the same for every tool."""

    def test_rule_on_the_ratio_and_the_score(self):
        self.assertTrue(V.covers("uneven", {"x": 2.0}))
        self.assertFalse(V.covers("uneven", {"x": 2.01}))
        self.assertTrue(V.covers("tensor", {"pts": 4}))
        self.assertFalse(V.covers("tensor", {"pts": 3}))
        self.assertFalse(V.covers("uneven", None))
        self.assertFalse(V.covers("thinning", {"x": math.inf}))

    def test_the_page_verdicts_follow_the_printed_ratios(self):
        for side, b in _worlds_page().items():
            for slug, dj in _json(b)["devices"].items():
                for f, per_tool in dj["vals"].items():
                    for tool, v in per_tool.items():
                        if v is None:
                            continue
                        if f == "compile":
                            continue                       # printed as a band ("1-10 s"), not a ratio
                        if f in V.MEASURED:
                            m = re.match(r"([\d.]+)×", v[1])
                            if m:
                                x = float(m.group(1))
                                if x < 2.0:                    # a printed 2.0 is floored: either verdict is possible there
                                    self.assertTrue(v[2], (side, slug, f, tool, v))
                                if x > 2.0:
                                    self.assertFalse(v[2], (side, slug, f, tool, v))
                            else:
                                self.assertEqual(v[2], 0, (side, slug, f, tool, v))       # "no saving" and the like
                        else:
                            m = re.match(r"(\d) of 5", v[0])
                            self.assertEqual(bool(v[2]), int(m.group(1)) >= V.RUBRIC_MIN, (side, slug, f, tool, v))

    def test_labels_match_the_site_axis_names(self):
        for k, lab in V.LABEL.items():
            if k in sc.RADAR_AXIS_EXTRA:
                self.assertEqual(lab, sc.RADAR_AXIS_EXTRA[k]["short"], k)


class TestTablesAndPopovers(unittest.TestCase):
    """2 and 4. The tables carry the blocks' coverage and every field the popover shows."""

    def test_block_table_matches_coverage(self):
        for side, slug in _all_devices():
            w = _worlds(side, slug, "wide")
            dev = dict(_devices(_worlds_page()[side]))[slug]
            for key in V.BLOCKS_KEYS:
                row = re.search(rf'<tr data-block="{key}">(.*?)</tr>', dev, re.S).group(1)
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row)[1:]
                for tool, cell in zip(w.tools, cells):
                    self.assertEqual(cell == "covered", V.block_covered(w.table, key, tool), (side, slug, key, tool))

    def test_popover_fields_are_in_the_tables(self):
        for side, b in _worlds_page().items():
            data = _json(b)["devices"]
            for slug, dev in _devices(b):
                dj = data[slug]
                tables = html.unescape(dev)
                for key, blk in dj["blocks"].items():
                    self.assertIn(html.escape(blk["l"]) if False else blk["l"], tables)
                    for f, label in blk["f"]:
                        self.assertIn(f'<tr data-feature="{f}">', dev)
                        self.assertIn(label, tables)
                    for tool in blk["w"]:
                        self.assertIn(tool, _tools(b))
                for f, per_tool in dj["vals"].items():
                    row = re.search(rf'<tr data-feature="{f}">(.*?)</tr>', dev, re.S).group(1)
                    cells = re.findall(r"<td class=\"[^\"]*\">(.*?)</td>", row, re.S)
                    names = _tools(b)
                    self.assertEqual(len(cells), len(names))
                    for tool, cell in zip(names, cells):
                        v = per_tool[tool]
                        text = html.unescape(re.sub(r"<[^>]+>", " ", cell))
                        if v is None:
                            self.assertEqual(html.unescape(cell), "no reading")
                            continue
                        self.assertIn(v[0], text)
                        if f in V.MEASURED and v[1]:
                            self.assertIn(v[1], text)
                        self.assertEqual("✓" in text, bool(v[2]), (slug, f, tool))

    def test_cpu_missing_readings_are_never_claimed(self):
        """CPU honesty: a tool with no reading on a feature shows 'no reading' and cannot cover a block that needs it."""
        checked = 0
        for side, slug in _all_devices():
            if side != "cpu":
                continue
            dj = _json(_worlds_page()[side])["devices"][slug]
            for f, per_tool in dj["vals"].items():
                for tool, v in per_tool.items():
                    if v is None:
                        checked += 1
                        for key, blk in dj["blocks"].items():
                            if f in [x[0] for x in blk["f"]] and f not in blk["x"]:
                                self.assertNotIn(tool, blk["w"], (slug, f, tool, key))
            for key, blk in dj["blocks"].items():            # a tool covers a block only through readings that all say so
                for tool in blk["w"]:
                    for f, _l in blk["f"]:
                        if f not in blk["x"]:
                            self.assertTrue(dj["vals"][f][tool] and dj["vals"][f][tool][2], (slug, key, tool, f))
        self.assertGreater(checked, 0)


class TestIcons(unittest.TestCase):
    """3. One registry of icons, inline, each element with a name."""

    def test_every_block_feature_and_sector_has_an_icon(self):
        for b in V.BLOCKS:
            self.assertIn(b[3], radar_icons.ICONS, b[0])
        for s in V.SECTORS:
            self.assertIn(s[3], radar_icons.ICONS, s[0])
        for f, _l, _k in V.FEATURES:
            self.assertIn(f, radar_icons.ICONS, f)

    def test_every_node_has_a_name_and_a_symbol(self):
        for side, b in list(_worlds_page().items()) + list(_rosette_page().items()):
            ids = set(re.findall(r'<symbol id="([^"]+)"', b))
            self.assertTrue(ids)
            for href in set(re.findall(r'<use href="#([^"]+)"', b)):
                self.assertIn(href, ids)
            for g in re.findall(r'<g class="(?:wnode|rnode|rsector)[^"]*"[^>]*>', b):
                self.assertRegex(g, r'aria-label="[^"]+"')
                self.assertIn('tabindex="0"', g)
            self.assertNotRegex(b, r'<(?:link|img)[^>]+(?:\.svg|\.png)')


class TestConvexityAndClearance(unittest.TestCase):
    """5. Every drawn blob is the rounded convex hull of its covered blocks, and every uncovered block clears it, on every card."""

    def test_drawn_shapes_are_the_hulls_on_every_card(self):
        for side, slug in _all_devices():
            dev = dict(_devices(_worlds_page()[side]))[slug]
            wide_html, narrow_html = dev.split('<div class="worlds-narrow">')
            for mode, part in (("wide", wide_html), ("narrow", narrow_html)):
                w = _worlds(side, slug, mode)
                drawn = _paths(part)
                want = [(t, blob.path()) for t in w.tools for blob, _m in w.pieces[t]]
                self.assertEqual(drawn, want, (side, slug, mode))
                for t in w.tools:
                    for blob, members in w.pieces[t]:
                        hull = V.convex_hull([w.pos[k] for k in members])
                        self.assertEqual(sorted(blob.hull), sorted(hull))
                        c = blob.core
                        if len(c) >= 3:
                            signs = {math.copysign(1, (c[(i + 1) % len(c)][0] - c[i][0]) * (c[(i + 2) % len(c)][1] - c[(i + 1) % len(c)][1])
                                                   - (c[(i + 1) % len(c)][1] - c[i][1]) * (c[(i + 2) % len(c)][0] - c[(i + 1) % len(c)][0])) for i in range(len(c))}
                            self.assertEqual(len(signs), 1, (side, slug, t, "core is not convex"))

    def test_uncovered_blocks_clear_every_outline(self):
        need = V.NODE_R + V.CLEAR
        for side, slug in _all_devices():
            for mode in ("wide", "narrow"):
                w = _worlds(side, slug, mode)
                self.assertEqual(w.violations, [], (side, slug, mode))
                nr = w.node
                for t in w.tools:
                    for blob, members in w.pieces[t]:
                        for k in V.BLOCKS_KEYS:
                            d = blob.distance(w.pos[k])
                            if k in members:
                                self.assertLessEqual(d, -(nr + V.CLEAR), (side, slug, mode, t, k, "not enclosed"))
                            elif k not in w.cov[t]:
                                self.assertGreaterEqual(d, nr + V.CLEAR, (side, slug, mode, t, k, "enclosed or too close"))
        self.assertEqual(need, 23)

    def test_drawn_arcs_bulge_outwards(self):
        """The drawn SVG outline, not only the geometry: the midpoint of every arc in a blob's path lies on that blob's
        outline. An arc swept the wrong way (an inward stadium cap) puts it deep inside and leaves blocks outside."""
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
        for side, slug in _all_devices():
            for mode in ("wide", "narrow"):
                w = _worlds(side, slug, mode)
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
                                self.assertLess(abs(blob.distance(mid)), 1.0, (side, slug, mode, t, "arc swept inwards"))
                                cur = nxt

    def test_raptor_is_never_split(self):
        for side, slug in _all_devices():
            for mode in ("wide", "narrow"):
                self.assertLessEqual(len(_worlds(side, slug, mode).pieces["raptor"]), 1)

    def test_the_fallback_cases_are_few_and_named(self):
        """Pieces beyond one hull are the ruled fallback; list them so a change that adds one is a visible edit here."""
        split = {}
        for side, slug in _all_devices():
            w = _worlds(side, slug, "wide")
            for t in getattr(w, "split", []):
                split.setdefault(side, set()).add((slug, t))
        for side, cases in split.items():
            self.assertTrue(all(t != "raptor" for _s, t in cases))
        self.assertEqual({t for cases in split.values() for _s, t in cases}, {"NVIDIA Warp"})


class TestLabels(unittest.TestCase):
    """6. Label non-intersection, both visuals, every card, wide and phone width, every rosette sector."""

    def test_worlds_labels_clear_everything(self):
        for side, slug in LABEL_CARDS:
            w = _worlds(side, slug, "wide")
            self.assertGreaterEqual(min(v["gap"] for v in w.labels.values()), MIN_GAP, (side, slug))
            for k, tt in w.titles().items():
                self.assertGreaterEqual(tt["gap"], MIN_GAP, (side, slug, k))
            for t, nb in w.name_boxes().items():
                self.assertGreaterEqual(nb["gap"], MIN_GAP, (side, slug, "name", t))
            # label vs label, recomputed from the boxes
            boxes = [v["box"][:4] for v in w.labels.values()]
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    self.assertGreaterEqual(V._box_gap(a, b), MIN_GAP)
            n = _worlds(side, slug, "narrow")
            for k, tt in n.titles().items():
                self.assertGreaterEqual(tt["gap"], MIN_GAP, (side, slug, k, "narrow"))

    def test_rosette_labels_clear_everything(self):
        for side, slug in LABEL_CARDS:
            b = _rosette_page()[side]
            tools = [(t, "") for t in _tools(b)]
            table = _table(_json(b)["devices"][slug])
            for mode, sector in [("wide", "ensemble")] + ([("narrow", s[0]) for s in V.SECTORS] if side == "gpu" else []):
                g = V.Rosette(table, tools, mode, sector).min_gaps()
                for kind, v in g.items():
                    self.assertGreaterEqual(v, MIN_GAP, (side, slug, mode, sector, kind))

    def test_nothing_leaves_the_phone_column(self):
        for side, slug in _all_devices():
            w = _worlds(side, slug, "narrow")
            width, height = w.lay["size"]
            for t in w.tools:
                for blob, _m in w.pieces[t]:
                    xs = [p[0] for p in blob.outline(6)]
                    ys = [p[1] for p in blob.outline(6)]
                    self.assertGreaterEqual(min(xs), 0, (side, slug, t))
                    self.assertLessEqual(max(xs), width, (side, slug, t))
                    self.assertGreaterEqual(min(ys), 0, (side, slug, t))
                    self.assertLessEqual(max(ys), height, (side, slug, t))
            for k, tt in w.titles().items():
                self.assertGreaterEqual(tt["box"][0], 0)
                self.assertLessEqual(tt["box"][2], width)


class TestHoverPolicy(unittest.TestCase):
    """7. A tool's blob and its chip are one handler; the drawn name is the chip's name; nothing is hover-only."""

    def test_blob_and_chip_share_one_handler(self):
        js = (SITE_ROOT / "_static" / "js" / "visuals.js").read_text()
        self.assertIn('".worlds-leg, path.blob[data-tool]"', js)
        for el in ("mouseenter", "mouseleave", "focus", "blur", "click"):
            self.assertIn(f'el.addEventListener("{el}"', js)

    def test_names_equal_chip_names(self):
        for side, b in _worlds_page().items():
            chips = _tools(b)
            for slug, dev in _devices(b):
                for t, d in _paths(dev):
                    self.assertIn(html.unescape(t), chips)
                for name in re.findall(r'<text class="bname" data-tool="([^"]+)"[^>]*>([^<]*)</text>', dev):
                    self.assertEqual(name[0], name[1])
                    self.assertIn(name[0], chips)

    def test_every_chip_names_its_tool_for_a_screen_reader(self):
        for side, b in _worlds_page().items():
            for t in _tools(b):
                self.assertIn(f'aria-label="{html.escape(t, quote=True)}"', b)


class TestCrossHighlight(unittest.TestCase):
    """8. One feature key links the rosette, the radar, the popover rows and the tables."""

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
    """The landing page: bars, then the two worlds, then the radar; the detail page: the toggle with the rosette first."""

    def test_landing_order_under_each_side(self):
        text = (GENERATED / "perf_switch.md").read_text()
        for side in ("gpu", "cpu"):
            i = text.index(f'<div class="perf-side perf-side-{side}">')
            seg = text[i:]
            self.assertLess(seg.index('<section class="perf-dev">'), seg.index('<div class="worlds"'))
            self.assertLess(seg.index('<div class="worlds"'), seg.index('<div class="radar"'))

    def test_detail_toggle(self):
        text = (GENERATED / "radar_detailed.md").read_text()
        for side in ("gpu", "cpu"):
            self.assertIn('data-view="rosette" aria-pressed="true">Rosette<', text)
            self.assertIn('data-view="radar" aria-pressed="false">Radar<', text)
        self.assertLess(text.index('<div class="vis-rosette">'), text.index('<div class="vis-radar">'))


class TestEarlyFinishBars(unittest.TestCase):
    """9. The third bars view."""

    def test_saving_formula(self):
        card = {"ns": [1000], "results": []}
        for arm, wu, ws, su, ss in (("eagle_simulate", 1.0, 0.4, 1000, 500), ("warp_kernel", 1.0, 0.9, 1000, 500)):
            card["results"].append({"arm": arm, "n": 1000, "distribution": "uniform", "max_steps": 1000, "wall_s": {"mean": wu, "median": wu, "min": wu},
                                    "sample_steps": su})
            card["results"].append({"arm": arm, "n": 1000, "distribution": "spread", "max_steps": 1000, "wall_s": {"mean": ws, "median": ws, "min": ws},
                                    "sample_steps": ss})
        sav = sc.early_saving_by_tool(card, "gpu")
        self.assertAlmostEqual(sav["raptor"][0], (1 - 0.4) / (1 - 0.5))
        self.assertAlmostEqual(sav["NVIDIA Warp"][0], (1 - 0.9) / (1 - 0.5))
        self.assertEqual(sc._fmt_saving(0.12), "12%")
        self.assertEqual(sc._fmt_saving(0.001), "none")

    def test_every_device_panel_has_the_view(self):
        text = (GENERATED / "perf_switch.md").read_text()
        panels = re.findall(r'<section class="perf-dev">(.*?)</section>', text, re.S)
        self.assertTrue(panels)
        for p in panels:
            self.assertIn('data-view="early" aria-pressed="false">Early-finish saving<', p)
            self.assertIn('class="bars-view bars-early"', p)
            self.assertIn(sc.EARLY_NOTE, p)
            self.assertIn("Early-finish saving on", p)


class TestPhoneLayout(unittest.TestCase):
    """10. At phone width the icons stand in for the labels, each reachable and named, with the key listed once."""

    def test_narrow_charts_have_no_label_text_and_a_key(self):
        for side, b in _worlds_page().items():
            for slug, dev in _devices(b):
                narrow = dev.split('<div class="worlds-narrow">')[1]
                svg = narrow.split("</svg>")[0]
                self.assertNotIn('class="nlabel', svg)
                self.assertEqual(len(re.findall(r'<li data-block="', narrow)), len(V.BLOCKS))
                self.assertEqual(len(re.findall(r'class="wnode', svg)), len(V.BLOCKS))

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
