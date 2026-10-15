# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The family's two coverage visuals, as one generator with no dependency on the site: the capability map (one tool at
a time; each capability is a row whose dot sits at CPU only, both, or GPU only) and the rosette (the radar's majors
fanned open, each tool's band over the features it covers).

The capability map reads a static, sourced table (``_data/capabilities.json``): tool x block x device -> covered or not,
with the source page and a one-line note for every covered cell. It is the same on every device and carries no
measurement; performance lives in the bars and the radar.

The rosette reads a feature table ``{feature: {tool: entry}}`` where an entry is ``{"v": value text, "r": ratio or
reason text, "a": arm, "x": ratio to the best (measured features), "pts": rubric score (judgement features)}``. A tool
covers a feature when it is within `WITHIN` times the best tool (measured) or scores at least `RUBRIC_MIN` (judgement):
the same rule as the radar, for every tool.

The rosette's geometry is computed here, in final drawing coordinates, so the label-gap checks the tests run read the
same numbers the markup is drawn from."""
import math

import radar_icons  # noqa: E402,F401  (the shared icon registry)

# --------------------------------------------------------------------------- features
#: Every feature of the visuals, in the rosette's order: (key, short label, kind).
FEATURES = (
    ("uneven", "Uneven ensembles", "m"), ("regular", "Regular ensembles", "m"), ("small", "Small jobs", "m"),
    ("adaptive", "Adaptive ODEs", "m"),
    ("uneven_eff", "Uneven-batch efficiency", "m"), ("memory", "Memory", "m"), ("compile", "Compile time", "m"),
    ("code", "Code size", "m"), ("tensor", "Tensors", "q"), ("array_style", "Array style", "q"),
    ("half_precision", "Half precision", "q"), ("single_thread", "Single-thread", "q"),
    ("differentiable", "Derivatives", "q"), ("control", "Control", "q"), ("arrays", "Your arrays", "q"),
    ("deploy", "Deploy", "q"), ("extensible", "Extensibility", "q"),
)
LABEL = {k: lab for k, lab, _kind in FEATURES}
MEASURED = frozenset(k for k, _l, kind in FEATURES if kind == "m")
#: A tool covers a measured feature within this multiple of the best tool, a judgement feature from this score.
WITHIN, RUBRIC_MIN = 2.0, 4

MONO = {"raptor": "r", "NVIDIA Warp": "W", "JAX": "J", "PyTorch": "Pt", "Numba": "Nb", "NumPy": "Np", "CuPy": "Cu"}


def covers(feature, entry):
    """Whether one tool's entry on a feature meets the coverage rule (None / no reading: no)."""
    if entry is None:
        return False
    if "ok" in entry:                       # a table rebuilt from the page's own JSON carries the verdict
        return bool(entry["ok"])
    if feature in MEASURED:
        x = entry.get("x")
        return x is not None and x <= WITHIN
    pts = entry.get("pts")
    return pts is not None and pts >= RUBRIC_MIN


def measured_anywhere(table, feature):
    """Whether any tool has a reading on the feature (a measured feature nobody has a reading on, such as a
    speed-of-light reference still pending, is left out of the blocks that need it rather than excluding every tool)."""
    return any(table.get(feature, {}).values())


def feature_covered(table, feature, tool):
    return covers(feature, table.get(feature, {}).get(tool))


# --------------------------------------------------------------------------- blocks
#: (key, label, label lines, icon, region). Region is "sim" or "ai": the column of the capability map the block sits in.
BLOCKS = (
    ("handtuned", "Hand-tuned kernels", ("Hand-tuned", "kernels"), "app-handtuned", "sim"),
    ("fixed", "Fixed-step ODEs", ("Fixed-step", "ODEs"), "regular", "sim"),
    ("deriv", "Differentiable sensitivities", ("Differentiable", "sensitivities"), "differentiable", "sim"),
    ("zerocopy", "Zero-copy hand-over (DLPack)", ("Zero-copy", "hand-over"), "arrays", "sim"),
    ("models", "Per-sample models and RHS", ("Per-sample", "models, RHS"), "single_thread", "sim"),
    ("half", "Half precision", ("Half", "precision"), "half_precision", "ai"),
    ("linalg", "Dense linear algebra, large solvers", ("Dense linear", "algebra, solvers"), "tensor", "ai"),
    ("ensembles", "Ensembles and Monte Carlo", ("Ensembles,", "Monte Carlo"), "app-ensemble", "sim"),
    ("divergent", "Divergent workloads", ("Divergent", "workloads"), "app-divergent", "sim"),
    ("events", "Events and early exit", ("Events,", "early exit"), "thinning", "sim"),
    ("adaptive", "Adaptive ODEs, embedded pairs", ("Adaptive ODEs,", "embedded pairs"), "adaptive", "sim"),
    ("deploy", "Deployment outside Python", ("Deploy outside", "Python"), "deploy", "sim"),
    ("diffsim", "Differentiable simulation into learning", ("Differentiable", "simulation"), "app-diffsim", "sim"),
    ("datagen", "Ensemble data for training", ("Ensemble data", "for training"), "app-datagen", "sim"),
    ("hybrid", "Hybrid, physics-informed models", ("Hybrid, physics-", "informed"), "app-hybrid", "ai"),
    ("training", "Dense tensor training", ("Dense tensor", "training"), "app-training", "ai"),
    ("inference", "Low-precision inference", ("Low-precision", "inference"), "app-inference", "ai"),
    ("arraystyle", "Array-style programs", ("Array-style", "programs"), "array_style", "ai"),
)
BLOCK = {b[0]: b for b in BLOCKS}
BLOCKS_KEYS = tuple(b[0] for b in BLOCKS)
#: The map's rows, top to bottom.
DEVICES = (("cpu", "CPU"), ("gpu", "GPU"))
DEVICE_NAME = dict(DEVICES)


def node_id(device, block):
    """The key of one block on one device row, as the layout, the markup and the JSON spell it."""
    return f"{device}:{block}"


def split_node(nid):
    device, block = nid.split(":")
    return device, block


#: The stops of a capability row's track, left to right: CPU only, CPU and GPU, GPU only.
STOPS = ("cpu", "both", "gpu")
STOP_NAME = {"cpu": "CPU", "both": "both", "gpu": "GPU", None: "none"}
WORLD_NAME = {"sim": "Simulation", "ai": "AI"}


class Capabilities:
    """The static, sourced coverage table: ``data`` as read from ``_data/capabilities.json``."""

    def __init__(self, data):
        self.data = data
        self.tools = list(data["tools"])
        self.needs = dict(data["blocks"])
        self.cells = data["cells"]
        self.xs = {k: float(v["x"]) for k, v in data["x"].items()}

    def y(self, tool, block):
        """The stored vertical position of a tool on a capability: -1 CPU only, 0 both, +1 GPU only, None not first-class."""
        return self.cells[tool][block]["y"]

    def cell(self, tool, block, device):
        return self.cells[tool][block][device]

    def covered(self, tool, block, device):
        return bool(self.cell(tool, block, device)["covered"])

    def stop(self, tool, block):
        """Where the tool's dot sits on the row: "cpu", "both", "gpu", or None when it covers the block on neither."""
        cpu, gpu = self.covered(tool, block, "cpu"), self.covered(tool, block, "gpu")
        return "both" if cpu and gpu else "cpu" if cpu else "gpu" if gpu else None

    def covered_blocks(self, tool):
        return [b for b in BLOCKS_KEYS if self.stop(tool, b)]

    def covered_cells(self):
        """[(block, device, tool, cell)] of every covered cell, in block, device, tool order."""
        return [(b, d, t, self.cell(t, b, d)) for b in BLOCKS_KEYS for d, _n in DEVICES for t in self.tools if self.covered(t, b, d)]

    def summary(self, tool):
        """One plain sentence: the count, the device spread, the world spread."""
        blocks = self.covered_blocks(tool)
        n = len(blocks)
        if not n:
            return f"{tool}: no capabilities in this list."
        stops = [self.stop(tool, b) for b in blocks]
        cnt = {k: stops.count(k) for k in STOPS}
        label = {"both": "on both CPU and GPU", "cpu": "CPU only", "gpu": "GPU only"}
        if max(cnt.values()) == n:
            dev = label[stops[0]]
        else:
            dev = ", ".join(f"{cnt[k]} {label[k]}" for k in ("both", "cpu", "gpu") if cnt[k])
        sim = sum(1 for b in blocks if BLOCK[b][4] == "sim")
        ai = n - sim
        if not ai:
            world = "all on the Simulation side"
        elif not sim:
            world = "all on the AI side"
        else:
            world = f"{sim} on the Simulation side and {ai} on the AI side"
        return f"{tool}: {n} {'capability' if n == 1 else 'capabilities'}, {dev}, {world}."


# --------------------------------------------------------------------------- text measure
_FONTS = {}
_FONT_FILES = ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf")


def text_width(text, size, bold=False):
    """Width of a line of text in px at ``size``: DejaVu Sans (a wide face, so a gap measured with it holds in the
    site's narrower faces) when Pillow and the font are there, else 0.62 em per character."""
    key = size
    if key not in _FONTS:
        _FONTS[key] = None
        try:
            from PIL import ImageFont
            for f in _FONT_FILES:
                try:
                    _FONTS[key] = ImageFont.truetype(f, int(round(size * 4)))
                    break
                except OSError:
                    continue
        except ImportError:
            pass
    f = _FONTS[key]
    w = f.getlength(text) / 4.0 if f else 0.62 * size * len(text)
    return w * (1.06 if bold else 1.0)


# --------------------------------------------------------------------------- the capability chart
#: Chart constants per width: viewBox width, left margin (axis labels), right margin, icon size, label font and line height,
#: gap icon->label, band padding, header height.
QUAD_MODES = {
    "wide": {"W": 920, "L": 104, "R": 12, "icon": 28, "fs": 11, "lh": 13, "gap": 4, "pad": 8, "head": 34, "cell_gap": 6},
    "narrow": {"W": 390, "L": 56, "R": 6, "icon": 22, "fs": 9.5, "lh": 11, "gap": 2, "pad": 4, "head": 28, "cell_gap": 2},
}
BANDS = ("cpu", "mid", "gpu")
BAND_NAME = {"cpu": "CPU", "mid": "CPU and GPU", "gpu": "GPU"}
BAND_OF_Y = lambda y: "cpu" if y <= -0.5 else "gpu" if y >= 0.5 else "mid"  # noqa: E731


class QuadChart:
    """The capability chart in one width: Simulation (left) to AI (right) across, CPU / CPU and GPU / GPU down. A capability's
    x is fixed; its band is the selected tool's stored y. Icons sit in cells of a fixed deterministic packing (by x order, the
    first sub-row where the cell does not touch the one before it), so nothing overlaps by construction; the number of
    sub-rows per band is the most any tool (or the no-tool strip) needs, so the chart never changes height."""

    def __init__(self, caps, mode):
        self.caps, self.mode = caps, mode
        c = self.c = QUAD_MODES[mode]
        self.lines = {k: BLOCK[k][2] for k in BLOCKS_KEYS}
        self.lab_w = {k: max(text_width(l, c["fs"]) for l in self.lines[k]) for k in BLOCKS_KEYS}
        self.cell_w = {k: max(c["icon"] + 6, self.lab_w[k] + 8) for k in BLOCKS_KEYS}
        self.m = max(self.cell_w.values()) / 2.0
        self.x0, self.x1 = c["L"] + self.m, c["W"] - c["R"] - self.m
        self.pitch = c["icon"] + c["gap"] + 2 * c["lh"] + 6
        self.states = {None: self._plan(None)}
        for t in caps.tools:
            self.states[t] = self._plan(t)
        rows = {b: max(self._rows(s_)[b] for s_ in self.states.values()) for b in BANDS}
        self.nrows = {"cpu": max(rows["cpu"], rows["gpu"], 1), "gpu": max(rows["cpu"], rows["gpu"], 1)}
        self.nrows["mid"] = max(rows["mid"], self.nrows["cpu"] + 1)
        top = c["head"]
        self.band = {}
        for b in BANDS:
            h = self.nrows[b] * self.pitch + 2 * c["pad"]
            self.band[b] = (top, top + h)
            top += h
        self.H = top + 6
        self.pos = {t: self._place(plan) for t, plan in self.states.items()}

    def px(self, block):
        return self.x0 + self.caps.xs[block] * (self.x1 - self.x0)

    def _plan(self, tool):
        """{block: (band, kind, sub-row)}: kind cov (a labelled icon in its band), ghost or neutral (a bare icon on the middle band)."""
        items = {b: [] for b in BANDS}
        for k in BLOCKS_KEYS:
            y = self.caps.y(tool, k) if tool else None
            if tool and y is not None:
                items[BAND_OF_Y(y)].append((k, "cov", self.cell_w[k]))
            else:
                items["mid"].append((k, "ghost" if tool else "neutral", self.c["icon"] + 6))
        plan = {}
        for b in BANDS:
            rights = []
            for k, kind, w in sorted(items[b], key=lambda it: (self.caps.xs[it[0]], BLOCKS_KEYS.index(it[0]))):
                cx = self.px(k)
                for r, right in enumerate(rights):
                    if cx - w / 2 >= right + self.c["cell_gap"]:
                        rights[r] = cx + w / 2
                        break
                else:
                    r = len(rights)
                    rights.append(cx + w / 2)
                plan[k] = (b, kind, r)
        return plan

    @staticmethod
    def _rows(plan):
        out = {b: 0 for b in BANDS}
        for b, _k, r in plan.values():
            out[b] = max(out[b], r + 1)
        return out

    def _place(self, plan):
        """{block: {x, y, band, kind, icon box, label box or None}} in viewBox coordinates (the icon centre is (x, y))."""
        c = self.c
        out = {}
        for k, (b, kind, r) in plan.items():
            cx = self.px(k)
            cy = self.band[b][0] + c["pad"] + r * self.pitch + c["icon"] / 2
            ic = (cx - c["icon"] / 2, cy - c["icon"] / 2, cx + c["icon"] / 2, cy + c["icon"] / 2)
            lab = None
            if kind == "cov":
                t0 = cy + c["icon"] / 2 + c["gap"]
                lab = (cx - self.lab_w[k] / 2, t0, cx + self.lab_w[k] / 2, t0 + len(self.lines[k]) * c["lh"])
            out[k] = {"x": cx, "y": cy, "band": b, "kind": kind, "icon": ic, "label": lab}
        return out

    def json(self):
        r = lambda v: round(v, 1)  # noqa: E731
        return {"size": [self.c["W"], round(self.H, 1)], "plot": [r(self.x0), r(self.x1)], "icon": self.c["icon"],
                "bands": {b: [r(a), r(z)] for b, (a, z) in self.band.items()},
                "pos": {(t or "none"): {k: [r(p["x"]), r(p["y"]), p["kind"]] for k, p in st.items()} for t, st in self.pos.items()}}


# --------------------------------------------------------------------------- label gaps (the rosette's checks)
def _gap(box, p):
    dx = max(box[0] - p[0], p[0] - box[2], 0.0)
    dy = max(box[1] - p[1], p[1] - box[3], 0.0)
    return math.hypot(dx, dy)


def _box_gap(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def _box_node_gap(box, c, r):
    return max(0.0, _gap(box, c) - r)


# --------------------------------------------------------------------------- rosette
#: The radar's majors fanned open, in the radar's order, plus the batches that thin out after Ensemble speed:
#: (key, name lines, features, icon).
SECTORS = (
    ("ensemble", ("Ensemble", "speed"), ("uneven", "regular", "small", "adaptive"), "uneven"),
    ("thinout", ("Batches that", "thin out"), ("uneven_eff",), "thinning"),
    ("footprint", ("Footprint and", "turnaround"), ("memory", "compile", "code"), "memory"),
    ("numerics", ("Tensors and", "precision"), ("tensor", "array_style", "half_precision"), "tensor"),
    ("authoring", ("One-sample", "authoring"), ("single_thread", "differentiable"), "single_thread"),
    ("lowlevel", ("Low-level", "control"), ("control",), "control"),
    ("reach", ("Reach",), ("arrays", "deploy", "extensible"), "deploy"),
)
SECTOR = {s[0]: s for s in SECTORS}
SECTOR_OF = {f: s[0] for s in SECTORS for f in s[2]}
FEATURE_LINES = {
    "uneven": ("Uneven", "ensembles"), "regular": ("Regular", "ensembles"), "small": ("Small jobs",), "adaptive": ("Adaptive", "ODEs"),
    "uneven_eff": ("Uneven-batch", "efficiency"), "memory": ("Memory",),
    "compile": ("Compile", "time"), "code": ("Code size",), "tensor": ("Tensors",), "array_style": ("Array style",),
    "half_precision": ("Half", "precision"), "single_thread": ("Single-", "thread"), "differentiable": ("Derivatives",),
    "control": ("Control",), "arrays": ("Your arrays",), "deploy": ("Deploy",), "extensible": ("Extensibility",)}
#: Pad of each tool's band round a feature (nested like the hulls of the worlds chart).
ROSETTE_PAD = {"raptor": 15, "NVIDIA Warp": 11, "Numba": 12, "JAX": 7, "PyTorch": 3, "NumPy": 3, "CuPy": 1}
ROSETTE_PAD_NARROW = {"raptor": 11, "NVIDIA Warp": 8, "Numba": 9, "JAX": 5, "PyTorch": 2, "NumPy": 2, "CuPy": 1}


def pol(cx, cy, r, a):
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc_path(cx, cy, r, a0, a1):
    x0, y0 = pol(cx, cy, r, a0)
    x1, y1 = pol(cx, cy, r, a1)
    return f"M{x0:.1f} {y0:.1f}A{r:.1f} {r:.1f} 0 {1 if abs(a1 - a0) > math.pi else 0} {1 if a1 >= a0 else 0} {x1:.1f} {y1:.1f}"


def _text_box(x, y, lines, anchor, fs, lh, bold=False):
    w = max(text_width(l, fs, bold) for l in lines)
    left = x - w / 2 if anchor == "middle" else (x if anchor == "start" else x - w)
    return (left, y - 0.95 * fs, left + w, y + (len(lines) - 1) * lh + 0.3 * fs)


class Rosette:
    """One device's rosette. ``mode`` "wide" draws every sector; "narrow" one sector (``sector``) fanned over 120 degrees.
    Nodes sit on one ring, a tool's band round the chain of consecutive features it covers, feature labels pushed radially
    outward beyond every band (at the node ring + the outermost band + 18), sector names further out."""

    def __init__(self, table, tools, mode="wide", sector="ensemble", device=""):
        self.table, self.tools, self.mode, self.sector, self.device = table, [t[0] for t in tools], mode, sector, device
        self.vars = dict((t[0], t[1]) for t in tools)
        wide = mode == "wide"
        self.W, self.H, self.cx, self.cy = (1000, 900, 500, 450) if wide else (390, 440, 195, 270)
        self.RN, self.NR, self.ISZ = (205, 18, 20) if wide else (135, 14, 16)
        self.fs, self.lh = 11, 13
        self.pads = ROSETTE_PAD if wide else ROSETTE_PAD_NARROW
        self.band_extra = 3 if wide else 2
        top = max(self.pads[t] for t in self.tools)
        self.outer = self.NR + top + self.band_extra
        self.RL = self.RN + self.outer + (18 if wide else 16)
        self.RW0 = 48
        self.RW1 = self.RL + (52 if wide else 46)
        self.RS = self.RW1 + 40
        self.ang, self.sect = {}, {}
        if wide:
            per = 2 * math.pi / 18
            a = -math.pi / 2 - 2 * per
            for sk, _n, feats, _i in SECTORS:
                self.sect[sk] = (a, a + len(feats) * per)
                for i, f in enumerate(feats):
                    self.ang[f] = a + (i + 0.5) * per
                a += len(feats) * per
        else:
            feats = SECTOR[sector][2]
            sec = math.radians(120)
            base = -math.pi / 2
            self.sect[sector] = (base - sec / 2, base + sec / 2)
            for j, f in enumerate(feats):
                self.ang[f] = base - sec / 2 + sec * (j + 0.5) / len(feats)
        self.features = list(self.ang)
        self.node_xy = {f: pol(self.cx, self.cy, self.RN, self.ang[f]) for f in self.features}
        self.bands = self._bands()
        self.labels = self._labels()
        self.names = self._names() if wide else {}

    def covered(self, f, tool):
        return feature_covered(self.table, f, tool)

    def _bands(self):
        """[(tool, [features of one chain], R, outline points)]: a chain is consecutive covered features of one sector."""
        out = []
        for tool in self.tools:
            R = self.NR + self.pads[tool] + self.band_extra
            for sk in self.sect:
                chain = []
                chains = []
                for f in SECTOR[sk][2]:
                    if self.covered(f, tool):
                        chain.append(f)
                    elif chain:
                        chains.append(chain)
                        chain = []
                if chain:
                    chains.append(chain)
                for ch in chains:
                    out.append((tool, ch, R, self._band_outline(ch, R)))
        return out

    def band_path(self, chain, R):
        cx, cy, RN = self.cx, self.cy, self.RN
        a0, a1 = self.ang[chain[0]], self.ang[chain[-1]]
        if len(chain) == 1:
            x, y = self.node_xy[chain[0]]
            return f"M{x - R:.1f} {y:.1f}A{R} {R} 0 1 0 {x + R:.1f} {y:.1f}A{R} {R} 0 1 0 {x - R:.1f} {y:.1f}Z"
        p = lambda r, a: pol(cx, cy, r, a)
        return (f"M{p(RN + R, a0)[0]:.1f} {p(RN + R, a0)[1]:.1f}" + arc_path(cx, cy, RN + R, a0, a1)[arc_path(cx, cy, RN + R, a0, a1).index("A"):]
                + f"A{R} {R} 0 0 1 {p(RN - R, a1)[0]:.1f} {p(RN - R, a1)[1]:.1f}"
                + f"A{RN - R:.1f} {RN - R:.1f} 0 0 0 {p(RN - R, a0)[0]:.1f} {p(RN - R, a0)[1]:.1f}"
                + f"A{R} {R} 0 0 1 {p(RN + R, a0)[0]:.1f} {p(RN + R, a0)[1]:.1f}Z")

    def _band_outline(self, chain, R, step=3.0):
        cx, cy, RN = self.cx, self.cy, self.RN
        a0, a1 = self.ang[chain[0]], self.ang[chain[-1]]
        pts = []
        if len(chain) == 1:
            x, y = self.node_xy[chain[0]]
            m = max(12, int(2 * math.pi * R / step))
            return [(x + R * math.cos(2 * math.pi * k / m), y + R * math.sin(2 * math.pi * k / m)) for k in range(m)]
        for r, ra, rb in ((RN + R, a0, a1), (RN - R, a1, a0)):
            m = max(2, int(abs(rb - ra) * r / step))
            pts += [pol(cx, cy, r, ra + (rb - ra) * k / m) for k in range(m + 1)]
        for ang, sgn in ((a1, 1), (a0, -1)):
            x, y = pol(cx, cy, RN, ang)
            m = max(4, int(math.pi * R / step))
            for k in range(m + 1):
                phi = math.pi * k / m
                pts.append((x + R * (math.cos(phi) * math.cos(ang) - sgn * math.sin(phi) * math.sin(ang)),
                            y + R * (math.cos(phi) * math.sin(ang) + sgn * math.sin(phi) * math.cos(ang))))
        return pts

    # ---- labels
    def _anchor(self, a):
        ca = math.cos(a)
        return "start" if ca > 0.3 else ("end" if ca < -0.3 else "middle")

    def _feature_label(self, f, extra=0.0):
        a = self.ang[f]
        lines = FEATURE_LINES[f]
        x, y = pol(self.cx, self.cy, self.RL + extra, a)
        sa = math.sin(a)
        n = len(lines)
        y0 = y - (n - 1) * self.lh / 2 + self.fs * 0.35
        if sa < -0.75:
            y0 = y - (n - 1) * self.lh
        elif sa > 0.75:
            y0 = y + self.fs
        anc = self._anchor(a)
        return {"x": x, "y": y0, "anchor": anc, "lines": lines, "box": _text_box(x, y0, lines, anc, self.fs, self.lh)}

    def _obstacles(self):
        circles = [(self.node_xy[f], self.NR + 2) for f in self.features]
        pts = [p for _t, _c, _r, o in self.bands for p in o]
        return circles, pts

    def _labels(self):
        circles, pts = self._obstacles()
        out = {}
        for f in self.features:
            best = None
            for extra in (0, 4, 8, 12, 18, 24):
                lab = self._feature_label(f, extra)
                g = 7.0
                for c, r in circles:
                    g = min(g, _box_node_gap(lab["box"], c, r))
                b = lab["box"]
                for p in pts:
                    if b[0] - 7 < p[0] < b[2] + 7 and b[1] - 7 < p[1] < b[3] + 7:
                        g = min(g, _gap(b, p))
                for o in out.values():
                    g = min(g, _box_gap(b, o["box"]))
                lab["gap"] = g
                if g >= 6 or best is None or g > best["gap"]:
                    best = lab
                if g >= 6:
                    break
            out[f] = best
        return out

    def _names(self):
        """Sector names with their icons, beyond the wedge edge; the icon sits at the text's inner side."""
        out = {}
        isz = 22
        for sk, lines, _f, icon in SECTORS:
            a0, a1 = self.sect[sk]
            am = (a0 + a1) / 2
            x, y = pol(self.cx, self.cy, self.RS, am)
            anc = self._anchor(am)
            lh = 17
            n = len(lines)
            if anc == "middle":
                w = max(text_width(l, 15, True) for l in lines)
                sa = math.sin(am)
                y0 = (y - (n - 1) * lh if sa < -0.75 else y + 15)
                box = (x - w / 2, y0 - 14, x + w / 2, y0 + (n - 1) * lh + 5)
                ix, iy = x - w / 2 - isz / 2 - 11, y0 + (n - 1) * lh / 2 - 5
                tx = x
            else:
                tx = x + (isz + 6 if anc == "start" else -(isz + 6))
                y0 = y - (n - 1) * lh / 2 + 5
                w = max(text_width(l, 15, True) for l in lines)
                left = tx if anc == "start" else tx - w
                box = (left, y0 - 14, left + w, y0 + (n - 1) * lh + 5)
                ix = x + (isz / 2 if anc == "start" else -isz / 2)
                iy = y0 + (n - 1) * lh / 2 - 5
            out[sk] = {"x": tx, "y": y0, "anchor": anc, "lines": lines, "box": box, "icon": (ix, iy, isz), "lh": lh,
                       "ibox": (ix - isz / 2, iy - isz / 2, ix + isz / 2, iy + isz / 2)}
        return out

    def min_gaps(self):
        """Smallest gap, px, of each kind over every label of this rosette: label-label, label-node, label-band, name-label."""
        circles, pts = self._obstacles()
        labs = list(self.labels.values())
        ll = min([_box_gap(a["box"], b["box"]) for i, a in enumerate(labs) for b in labs[i + 1:]] or [1e9])
        ln = min([_box_node_gap(l["box"], c, r) for l in labs for c, r in circles] or [1e9])
        lb = min([_gap(l["box"], p) for l in labs for p in pts] or [1e9])
        nm = [v["box"] for v in self.names.values()] + [v["ibox"] for v in self.names.values()]
        nl = min([_box_gap(a, l["box"]) for a in nm for l in labs] + [_box_gap(a, b) for i, a in enumerate(nm) for b in nm[i + 1:]] or [1e9])
        return {"label_label": ll, "label_node": ln, "label_band": lb, "name_label": nl}
