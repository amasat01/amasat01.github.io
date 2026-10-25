# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The capability chart, as a generator with no dependency on the site: one tool at a time, each capability an icon placed
Simulation (left) to AI (right) and CPU / CPU and GPU / GPU (down).

It reads a static, sourced table (``_data/capabilities.json``): tool x block x device -> covered or not, with the source
page and a one-line note for every covered cell, a grade from 0 to 5 per tool and capability (with its reason and source),
a fixed x per capability and a stored y per tool. It is the same on every
device and carries no measurement; performance lives in the bars and the radar.

Geometry is computed here, in final drawing coordinates, so the overlap checks the tests run read the same numbers the
markup is drawn from."""
import math

MONO = {"raptor": "r", "NVIDIA Warp": "W", "JAX": "J", "PyTorch": "Pt", "Numba": "Nb", "NumPy": "Np", "CuPy": "Cu"}


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
    ("hostgpu", "Host and GPU steps in one graph", ("Host and GPU", "in one graph"), "arrays", "sim"),
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

    def grade(self, tool, block):
        """The tool's grade on a capability: {g: 0-5, reason, source, kind}, or None when no source confirms one."""
        return self.cells[tool][block]["g"]

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
    "wide": {"W": 720, "L": 92, "R": 12, "icon": 28, "fs": 11.5, "lh": 13.5, "gsz": 6.5, "gap": 6, "pad": 8, "head": 34, "cell_gap": 8, "vpad": 6},
    "narrow": {"W": 340, "L": 52, "R": 4, "icon": 22, "fs": 11, "lh": 12.5, "gsz": 6, "gap": 4, "pad": 4, "head": 26, "cell_gap": 4, "vpad": 5},
}
BANDS = ("cpu", "mid", "gpu")
BAND_NAME = {"cpu": "CPU", "mid": "CPU and GPU", "gpu": "GPU"}
BAND_OF_Y = lambda y: "cpu" if y <= -0.5 else "gpu" if y >= 0.5 else "mid"  # noqa: E731


class QuadChart:
    """The capability chart in one width: Simulation (left) to AI (right) across, CPU / CPU and GPU / GPU down. A capability's
    x is fixed; its band is the selected tool's stored y. A labelled icon is a cell (icon, then its name to the right, or to
    the left when the name would leave the chart); cells are packed by a fixed deterministic rule (by left edge, the first
    sub-row where the cell does not touch the one before it), so nothing overlaps by construction. The number of sub-rows per
    band is the most any tool (or the no-tool strip) needs, so the chart never changes height."""

    def __init__(self, caps, mode):
        self.caps, self.mode = caps, mode
        c = self.c = QUAD_MODES[mode]
        self.lines = {k: BLOCK[k][2] for k in BLOCKS_KEYS}
        self.lab_w = {k: max(text_width(l, c["fs"]) for l in self.lines[k]) for k in BLOCKS_KEYS}
        self.lab_h = {k: len(self.lines[k]) * c["lh"] for k in BLOCKS_KEYS}
        self.x0 = c["L"] + c["icon"] / 2 + 4
        self.x1 = c["W"] - c["R"] - c["icon"] / 2 - 4
        self.side = {k: "l" if self.px(k) + c["icon"] / 2 + c["gap"] + self.lab_w[k] > c["W"] - c["R"] - 2 else "r" for k in BLOCKS_KEYS}
        self.pitch = max(c["icon"], max(self.lab_h.values())) + c["vpad"]
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

    def cell(self, block, labelled):
        """(left, right) of a block's cell: its icon and, when labelled, its name on the side the chart allows."""
        c, cx = self.c, self.px(block)
        l, r = cx - c["icon"] / 2, cx + c["icon"] / 2
        if labelled:
            if self.side[block] == "r":
                r += c["gap"] + self.lab_w[block]
            else:
                l -= c["gap"] + self.lab_w[block]
        return l, r

    def _plan(self, tool):
        """{block: (band, kind, sub-row)}: kind cov (a labelled icon in its band), ghost or neutral (a bare icon on the middle band)."""
        items = {b: [] for b in BANDS}
        for k in BLOCKS_KEYS:
            y = self.caps.y(tool, k) if tool else None
            if tool and y is not None:
                items[BAND_OF_Y(y)].append((k, "cov"))
            else:
                items["mid"].append((k, "ghost" if tool else "neutral"))
        plan = {}
        for b in BANDS:
            rights = []
            for k, kind in sorted(items[b], key=lambda it: (self.cell(it[0], it[1] == "cov")[0], BLOCKS_KEYS.index(it[0]))):
                l, r_ = self.cell(k, kind == "cov")
                for r, right in enumerate(rights):
                    if l >= right + self.c["cell_gap"]:
                        rights[r] = r_
                        break
                else:
                    r = len(rights)
                    rights.append(r_)
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
            cy = self.band[b][0] + c["pad"] + r * self.pitch + self.pitch / 2 - c["vpad"] / 2
            ic = (cx - c["icon"] / 2, cy - c["icon"] / 2, cx + c["icon"] / 2, cy + c["icon"] / 2)
            lab = None
            if kind == "cov":
                if self.side[k] == "r":
                    lx = cx + c["icon"] / 2 + c["gap"]
                else:
                    lx = cx - c["icon"] / 2 - c["gap"] - self.lab_w[k]
                lab = (lx, cy - self.lab_h[k] / 2, lx + self.lab_w[k], cy + self.lab_h[k] / 2)
            out[k] = {"x": cx, "y": cy, "band": b, "kind": kind, "icon": ic, "label": lab}
        return out

    def json(self):
        r = lambda v: round(v, 1)  # noqa: E731
        return {"size": [self.c["W"], round(self.H, 1)], "plot": [r(self.x0), r(self.x1)], "icon": self.c["icon"],
                "bands": {b: [r(a), r(z)] for b, (a, z) in self.band.items()}, "side": self.side,
                "pos": {(t or "none"): {k: [r(p["x"]), r(p["y"]), p["kind"]] for k, p in st.items()} for t, st in self.pos.items()}}


# --------------------------------------------------------------------------- box gap (the chart's overlap check)
def _box_gap(a, b):
    """Distance between two boxes (left, top, right, bottom); 0 when they touch or overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)
