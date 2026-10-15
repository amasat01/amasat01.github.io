# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The family's two coverage visuals, as one generator with no dependency on the site: the capability map (blocks of
work on the CPU and on the GPU, each tool's rounded convex hull over the blocks it has a documented, first-class way to
do) and the rosette (the radar's majors fanned open, each tool's band over the features it covers).

The capability map reads a static, sourced table (``_data/capabilities.json``): tool x block x device -> covered or not,
with the source page and a one-line note for every covered cell. It is the same on every device and carries no
measurement; performance lives in the bars and the radar.

The rosette reads a feature table ``{feature: {tool: entry}}`` where an entry is ``{"v": value text, "r": ratio or
reason text, "a": arm, "x": ratio to the best (measured features), "pts": rubric score (judgement features)}``. A tool
covers a feature when it is within `WITHIN` times the best tool (measured) or scores at least `RUBRIC_MIN` (judgement):
the same rule as the radar, for every tool.

Geometry is computed here, in final drawing coordinates, so the checks the tests run (convexity, clearance, label gaps)
read the same numbers the markup is drawn from."""
import html
import itertools
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


class Capabilities:
    """The static, sourced coverage table: ``data`` as read from ``_data/capabilities.json``."""

    def __init__(self, data):
        self.data = data
        self.tools = list(data["tools"])
        self.needs = dict(data["blocks"])
        self.cells = data["cells"]

    def cell(self, tool, block, device):
        return self.cells[tool][block][device]

    def covered(self, tool, block, device):
        return bool(self.cell(tool, block, device)["covered"])

    def who(self, block, device):
        """The tools that cover a block on a device, in the table's tool order."""
        return [t for t in self.tools if self.covered(t, block, device)]

    def nodes(self):
        """Every (device, block) that at least one tool covers: the blocks the map draws on each row."""
        return [node_id(d, b) for d, _n in DEVICES for b in BLOCKS_KEYS if self.who(b, d)]

    def covered_nodes(self, tool):
        return [n for n in self.nodes() if self.covered(tool, *split_node(n)[::-1])]

    def covered_cells(self):
        """[(block, device, tool, cell)] of every covered cell, in block, device, tool order."""
        return [(b, d, t, self.cell(t, b, d)) for b in BLOCKS_KEYS for d, _n in DEVICES for t in self.tools if self.covered(t, b, d)]


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


# --------------------------------------------------------------------------- geometry
def convex_hull(points):
    """Andrew's monotone chain: the hull vertices, counter-clockwise in a y-up frame (clockwise on screen);
    collinear points drop out, so a set on one line is its two end points."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def hull_clearance(hull, p):
    """Signed distance from ``p`` to the convex polygon ``hull`` (negative inside); a point or a segment is a
    degenerate hull with no inside."""
    if len(hull) == 1:
        return math.dist(hull[0], p)
    if len(hull) == 2:
        return _seg_dist(p, hull[0], hull[1])
    d = min(_seg_dist(p, hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull)))
    inside = all((hull[(i + 1) % len(hull)][0] - hull[i][0]) * (p[1] - hull[i][1])
                 - (hull[(i + 1) % len(hull)][1] - hull[i][1]) * (p[0] - hull[i][0]) >= 0 for i in range(len(hull)))
    return -d if inside else d


def _clip(poly, a, b, c):
    """Keep the part of the convex polygon with a*x + b*y + c >= 0 (Sutherland-Hodgman, one half plane)."""
    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        fp, fq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if fp >= 0:
            out.append(p)
        if (fp >= 0) != (fq >= 0):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def _dedupe(poly, eps=1e-6):
    out = []
    for p in poly:
        if not out or math.dist(out[-1], p) > eps:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= eps:
        out.pop()
    return out


def erode(hull, d):
    """The convex polygon ``hull`` (n >= 3) moved inwards by ``d`` on every edge (None when nothing is left)."""
    poly = list(hull)
    n = len(hull)
    area2 = sum(hull[i][0] * hull[(i + 1) % n][1] - hull[(i + 1) % n][0] * hull[i][1] for i in range(n))
    sgn = 1.0 if area2 > 0 else -1.0
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L * sgn, dx / L * sgn            # the inward normal
        poly = _clip(poly, nx, ny, -(nx * a[0] + ny * a[1]) - d)
        if len(poly) < 3:
            return None
    poly = _dedupe(poly)
    return poly if len(poly) >= 3 else None


class Blob:
    """One rounded convex hull: the convex polygon ``core`` (a point, a segment or n >= 3 vertices) grown by the
    disc of radius ``r``. ``hull`` is the covered blocks' convex hull it was made from and ``pad`` the tool's pad
    (the outer offset of every edge); ``r - pad`` is how far the core was pulled in first, so a corner turns on the
    larger radius ``r`` while the edges stay where the pad puts them."""

    def __init__(self, hull, pad, inset=0.0, keep=0.0):
        self.hull, self.pad = list(hull), pad
        self.inset = 0.0
        self.core = list(hull)
        self.r = pad
        if len(hull) >= 3 and inset > 0:
            # the largest pull-in up to ``inset`` that leaves every vertex (the centre of a covered block) ``keep`` px inside
            lo, hi = 0.0, float(inset)
            for _ in range(14):
                mid = (lo + hi) / 2
                core = erode(hull, mid)
                ok = core is not None
                if ok:
                    self.core, self.inset, self.r = core, mid, pad + mid
                    ok = all(self.distance(v) <= -keep for v in hull)
                if ok:
                    lo = mid
                else:
                    hi = mid
            core = erode(hull, lo) if lo > 0 else None
            if core is None:
                self.core, self.inset, self.r = list(hull), 0.0, pad
            else:
                self.core, self.inset, self.r = core, lo, pad + lo

    def distance(self, p):
        """Signed distance from ``p`` to the outline (negative inside)."""
        return hull_clearance(self.core, p) - self.r

    def path(self):
        """The outline as one SVG path of exact arcs: edges offset outwards by ``r``, a circular arc round every
        corner (a stadium for two points, a circle for one)."""
        c, r = self.core, self.r
        if len(c) == 1:
            x, y = c[0]
            return f"M{x - r:.1f} {y:.1f}A{r:.1f} {r:.1f} 0 1 0 {x + r:.1f} {y:.1f}A{r:.1f} {r:.1f} 0 1 0 {x - r:.1f} {y:.1f}Z"
        if len(c) == 2:
            (x0, y0), (x1, y1) = c
            L = math.hypot(x1 - x0, y1 - y0)
            nx, ny = -(y1 - y0) / L * r, (x1 - x0) / L * r
            return (f"M{x0 + nx:.1f} {y0 + ny:.1f}L{x1 + nx:.1f} {y1 + ny:.1f}A{r:.1f} {r:.1f} 0 0 0 {x1 - nx:.1f} {y1 - ny:.1f}"
                    f"L{x0 - nx:.1f} {y0 - ny:.1f}A{r:.1f} {r:.1f} 0 0 0 {x0 + nx:.1f} {y0 + ny:.1f}Z")
        n = len(c)
        area2 = sum(c[i][0] * c[(i + 1) % n][1] - c[(i + 1) % n][0] * c[i][1] for i in range(n))
        sgn = 1.0 if area2 > 0 else -1.0
        # outward normal of edge i, and the sweep that walks the outline in the polygon's own orientation
        norm = []
        for i in range(n):
            a, b = c[i], c[(i + 1) % n]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            norm.append(((b[1] - a[1]) / L * sgn, -(b[0] - a[0]) / L * sgn))
        parts = []
        for i in range(n):
            a, b = c[i], c[(i + 1) % n]
            nx, ny = norm[i]
            mx, my = norm[(i + 1) % n]
            if i == 0:
                parts.append(f"M{a[0] + nx * r:.2f} {a[1] + ny * r:.2f}")
            parts.append(f"L{b[0] + nx * r:.2f} {b[1] + ny * r:.2f}")
            # two decimals: a corner that turns only a little has a short chord, and 0.1 px rounding of its ends
            # moves the arc's centre by pixels
            # sweep from the turn itself, so the arc is the one centred on the corner (never its mirror image)
            turn = nx * my - ny * mx
            parts.append(f"A{r:.2f} {r:.2f} 0 0 {1 if turn > 0 else 0} {b[0] + mx * r:.2f} {b[1] + my * r:.2f}")
        return "".join(parts) + "Z"

    def outline(self, step=3.0):
        """Points of the outline, about ``step`` px apart (what the label-gap checks sample)."""
        c, r = self.core, self.r
        pts = []
        if len(c) == 1:
            m = max(12, int(2 * math.pi * r / step))
            return [(c[0][0] + r * math.cos(2 * math.pi * k / m), c[0][1] + r * math.sin(2 * math.pi * k / m)) for k in range(m)]
        n = len(c)
        edges = [(c[0], c[1]), (c[1], c[0])] if n == 2 else [(c[i], c[(i + 1) % n]) for i in range(n)]
        if n == 2:
            ang = [math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0]) for e in edges]
            for (a, b), th in zip(edges, ang):
                nx, ny = math.sin(th), -math.cos(th)
                steps = max(1, int(math.dist(a, b) / step))
                pts += [(a[0] + (b[0] - a[0]) * k / steps + nx * r, a[1] + (b[1] - a[1]) * k / steps + ny * r) for k in range(steps)]
                m = max(4, int(math.pi * r / step))
                pts += [(b[0] + r * math.cos(th - math.pi / 2 + math.pi * k / m), b[1] + r * math.sin(th - math.pi / 2 + math.pi * k / m)) for k in range(m)]
            return pts
        area2 = sum(c[i][0] * c[(i + 1) % n][1] - c[(i + 1) % n][0] * c[i][1] for i in range(n))
        sgn = 1.0 if area2 > 0 else -1.0
        for i in range(n):
            a, b = edges[i]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            nx, ny = (b[1] - a[1]) / L * sgn, -(b[0] - a[0]) / L * sgn
            steps = max(1, int(L / step))
            pts += [(a[0] + (b[0] - a[0]) * k / steps + nx * r, a[1] + (b[1] - a[1]) * k / steps + ny * r) for k in range(steps)]
            a2, b2 = edges[(i + 1) % n]
            L2 = math.hypot(b2[0] - a2[0], b2[1] - a2[1])
            mx, my = (b2[1] - a2[1]) / L2 * sgn, -(b2[0] - a2[0]) / L2 * sgn
            t0, t1 = math.atan2(ny, nx), math.atan2(my, mx)
            da = (t1 - t0 + math.pi) % (2 * math.pi) - math.pi
            m = max(2, int(abs(da) * r / step))
            pts += [(b[0] + r * math.cos(t0 + da * k / m), b[1] + r * math.sin(t0 + da * k / m)) for k in range(m)]
        return pts

    def top(self):
        return min(p[1] for p in self.outline())


def rounded_hull_path(hull, pad, inset=0.0):
    """The drawn shape of a hull: `Blob(hull, pad, inset).path()`. The tests compare every drawn blob with this."""
    return Blob(hull, pad, inset).path()


# --------------------------------------------------------------------------- capability map layout
NODE_R, CLEAR = 19, 4


def _rows(spec, dy=0.0):
    return {k: (float(x), float(y) + dy) for k, (x, y) in spec.items()}


#: The two layouts of the capability map: block centres per device row, the column boundary between Simulation (left)
#: and AI (right), the row boundary between CPU (top) and GPU (bottom), node and icon sizes, and the viewBox. Positions
#: were searched so that every tool's padded hull is one convex piece that clears every block it does not cover: the
#: blocks only raptor does in a first-class way (adaptive, events, divergent) sit on the outer lines, the blocks nearly
#: every tool does (fixed-step, ensembles, data, zero-copy) on the lines next to the row boundary, "hybrid" at the edge
#: of the AI column, next to raptor's other blocks. The rows are nearly mirror images; where they differ, a tool covers
#: a block on one device only.
CAPMAP_LAYOUT = {
    "wide": {
        "size": (1040, 780), "node": NODE_R, "icon": 21, "fs": 11, "pad_scale": 1.0, "cols": 700.0, "rows": 416.0,
        "pos": _rows({
            "cpu:adaptive": (100, 80), "cpu:divergent": (247, 80), "cpu:events": (353, 80), "cpu:handtuned": (524, 80),
            "cpu:training": (990, 80), "cpu:diffsim": (238, 185), "cpu:fixed": (479, 185), "cpu:ensembles": (586, 185),
            "cpu:linalg": (759, 185), "cpu:half": (865, 185), "cpu:arraystyle": (982, 185), "cpu:deploy": (100, 290),
            "cpu:deriv": (207, 290), "cpu:models": (427, 290), "cpu:datagen": (539, 290), "cpu:zerocopy": (650, 290),
            "cpu:hybrid": (825, 290), "cpu:inference": (981, 290),
            "gpu:deploy": (100, 430), "gpu:deriv": (207, 430), "gpu:models": (427, 430), "gpu:datagen": (540, 430),
            "gpu:zerocopy": (650, 430), "gpu:hybrid": (828, 430), "gpu:inference": (981, 430), "gpu:diffsim": (339, 535),
            "gpu:fixed": (478, 535), "gpu:ensembles": (586, 535), "gpu:linalg": (835, 535), "gpu:arraystyle": (982, 535),
            "gpu:adaptive": (100, 640), "gpu:divergent": (247, 640), "gpu:events": (353, 640), "gpu:handtuned": (524, 640),
            "gpu:half": (788, 640), "gpu:training": (990, 640)}, dy=56),
    },
    # the phone column: CPU over GPU, four lines a row, icons only (the key list under the chart names them)
    "narrow": {
        "size": (390, 700), "node": 13, "icon": 16, "fs": 0, "pad_scale": 0.66, "cols": 268.0, "rows": 365.0,
        "pos": _rows({
            "cpu:divergent": (93, 50), "cpu:events": (152, 50), "cpu:handtuned": (216, 50), "cpu:training": (299, 50),
            "cpu:inference": (347, 50), "cpu:adaptive": (48, 130), "cpu:models": (211, 130), "cpu:linalg": (299, 130),
            "cpu:arraystyle": (350, 130), "cpu:deploy": (47, 212), "cpu:datagen": (158, 210), "cpu:fixed": (251, 210),
            "cpu:half": (335, 210), "cpu:diffsim": (59, 290), "cpu:deriv": (106, 290), "cpu:ensembles": (170, 290),
            "cpu:zerocopy": (252, 290), "cpu:hybrid": (334, 290),
            "gpu:diffsim": (59, 360), "gpu:deriv": (107, 360), "gpu:datagen": (159, 360), "gpu:ensembles": (205, 360),
            "gpu:zerocopy": (252, 360), "gpu:hybrid": (334, 360), "gpu:deploy": (104, 440), "gpu:fixed": (252, 440),
            "gpu:linalg": (336, 440), "gpu:adaptive": (48, 520), "gpu:models": (213, 520), "gpu:half": (291, 520),
            "gpu:arraystyle": (350, 520), "gpu:divergent": (93, 600), "gpu:events": (152, 600), "gpu:handtuned": (219, 600),
            "gpu:training": (296, 600), "gpu:inference": (347, 600)}, dy=40),
    },
}
#: Pad of each tool's hull (the outer offset of its outline from the blocks it covers), nested so the shapes of tools
#: that share blocks stay distinct. CuPy (GPU only) and NumPy (CPU only) never share a row, so they share a pad.
CAPMAP_PAD = {"raptor": 46, "JAX": 41, "PyTorch": 37, "NVIDIA Warp": 33, "Numba": 30, "CuPy": 27, "NumPy": 27}
#: How far a hull is pulled in before it is grown by pad + inset: a rounder corner, edges unchanged (see `Blob`).
CAPMAP_INSET = 40
#: Tools allowed to be drawn in more than one convex piece (the ruled fallback), with the reason. Empty: every tool's
#: covered blocks are one convex hull that clears every block it does not cover, in both layouts.
FALLBACK = {}
#: Where a label sits relative to its node by default, and the order the others are tried in.
LABEL_SIDES = ("b", "a", "r", "l")
#: Per-node forced label sides, each with its reason. Empty: the choice is made by gap measurement.
SIDE_FORCE = {}


# --------------------------------------------------------------------------- label placement
def _box_for(x, y, lines, side, node, fs, lh):
    """(left, top, right, bottom, anchor, x of text, baseline of the first line) of a block label."""
    w = max(text_width(l, fs) for l in lines)
    n = len(lines)
    asc, desc = 0.95 * fs, 0.3 * fs
    if side == "b":
        base, tx, anc = y + node + 17, x, "middle"
    elif side == "a":
        base, tx, anc = y - node - 11 - (n - 1) * lh, x, "middle"
    elif side == "r":
        base, tx, anc = y - (n - 1) * lh / 2 + 0.35 * fs, x + node + 8, "start"
    else:
        base, tx, anc = y - (n - 1) * lh / 2 + 0.35 * fs, x - node - 8, "end"
    left = tx - w / 2 if anc == "middle" else (tx if anc == "start" else tx - w)
    return (left, base - asc, left + w, base + (n - 1) * lh + desc, anc, tx, base)


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


class CapMap:
    """The capability map in one layout: the drawn nodes (a block on a device row), each tool's pieces (rounded convex
    hulls), the clearance violations (a layout bug when not empty) and the label placement. ``caps`` is a
    `Capabilities`; ``tools`` the drawn ``[(name, css var)]``; ``layout`` one of `CAPMAP_LAYOUT`."""

    def __init__(self, caps, tools, layout):
        self.caps, self.tools, self.lay = caps, [t[0] for t in tools], layout
        self.vars = dict((t[0], t[1]) for t in tools)
        self.nodes = caps.nodes()
        self.pos = {n: layout["pos"][n] for n in self.nodes}
        self.node = layout["node"]
        scale = layout.get("pad_scale", 1.0)
        self.pads = {t: CAPMAP_PAD.get(t, 24) * scale for t in self.tools}
        self.inset = CAPMAP_INSET * scale
        self.cov = {t: caps.covered_nodes(t) for t in self.tools}
        self.pieces = {}          # tool -> [(blob, [node ids])]
        self.violations = []
        self.split = []
        for t in self.tools:
            self.pieces[t] = self._pieces(t)
        self.labels = {}
        if layout["fs"]:
            self._place_labels()

    def who(self, nid):
        device, block = split_node(nid)
        return [t for t in self.tools if self.caps.covered(t, block, device)]

    # ---- hulls and clearance
    def _blob(self, tool, members):
        return Blob(convex_hull([self.pos[k] for k in members]), self.pads[tool], self.inset, keep=self.node + CLEAR)

    def _clearance_errors(self, tool, blob, members):
        """Every node the outline must clear (not covered by the tool) and every member it must enclose."""
        bad = []
        need = self.node + CLEAR
        for k in self.nodes:
            d = blob.distance(self.pos[k])
            if k in members:
                if d > -need:
                    bad.append((tool, k, "inside", round(d, 1), -need))
            elif k not in self.cov[tool] and d < need:
                bad.append((tool, k, "outside", round(d, 1), need))
        return bad

    def _pieces(self, tool):
        """One piece, the hull of everything the tool covers on both rows. Only a tool named in `FALLBACK` (never raptor,
        whose hull is convex above all) may be drawn as several convex hulls instead: start from one piece per node and
        join the two nearest pieces whenever the joined hull is clear. Anything not clear is reported in ``violations``."""
        cov = self.cov[tool]
        if not cov:
            return []
        whole = self._blob(tool, cov)
        errs = self._clearance_errors(tool, whole, cov)
        if not errs or tool == "raptor" or tool not in FALLBACK:
            self.violations += errs
            return [(whole, list(cov))]
        groups = [[k] for k in cov]
        while len(groups) > 1:
            cand = sorted(((math.dist(self._centre(a), self._centre(b)), i, j) for i, a in enumerate(groups) for j, b in enumerate(groups) if i < j))
            for _d, i, j in cand:
                merged = groups[i] + groups[j]
                if not self._clearance_errors(tool, self._blob(tool, merged), merged):
                    groups = [g for n, g in enumerate(groups) if n not in (i, j)] + [merged]
                    break
            else:
                break
        out = []
        for g in sorted(groups, key=lambda g: (-len(g), g)):
            b = self._blob(tool, g)
            self.violations += self._clearance_errors(tool, b, g)
            out.append((b, g))
        self.split.append(tool)
        return out

    def _centre(self, members):
        return (sum(self.pos[k][0] for k in members) / len(members), sum(self.pos[k][1] for k in members) / len(members))

    def min_clearance(self):
        """Smallest (distance to the outline minus node radius) over every uncovered node of every tool, px."""
        worst = None
        for t in self.tools:
            for blob, _members in self.pieces[t]:
                for k in self.nodes:
                    if k not in self.cov[t]:
                        d = blob.distance(self.pos[k]) - self.node
                        worst = d if worst is None else min(worst, d)
        return worst

    # ---- labels
    def _obstacles(self):
        circles = [(self.pos[k], self.node + 2) for k in self.nodes]
        pts = [p for t in self.tools for blob, _m in self.pieces[t] for p in blob.outline(4.0)]
        return circles, pts

    def _score(self, box, circles, pts, placed):
        """Smallest gap from the label box to any obstacle, capped at 7 px (nothing further matters); a box outside
        the viewBox scores below zero."""
        g = 7.0
        w, h = self.lay["size"]
        g = min(g, box[0] - 2, w - 2 - box[2], box[1] - 2, h - 2 - box[3])
        for c, r in circles:
            g = min(g, _box_node_gap(box, c, r))
        l, t, r_, b = box[0] - 7, box[1] - 7, box[2] + 7, box[3] + 7
        for p in pts:
            if l < p[0] < r_ and t < p[1] < b:
                g = min(g, _gap(box, p))
        for other in placed.values():
            g = min(g, _box_gap(box, other["box"][:4]))
        return g

    def _place_labels(self):
        circles, pts = self._obstacles()
        fs, lh = self.lay["fs"], self.lay["fs"] + 1
        placed = {}
        order = list(self.nodes) * 3                 # three passes: each label is re-placed against the others' final places
        for k in order:
            placed.pop(k, None)
            x, y = self.pos[k]
            lines = BLOCK[split_node(k)[1]][2]
            sides = (SIDE_FORCE[k],) if k in SIDE_FORCE else LABEL_SIDES
            best = None
            for rank, side in enumerate(sides):
                for ddx, ddy in ((0, 0), (-12, 0), (12, 0), (0, 6), (0, -6), (-24, 0), (24, 0), (0, 12), (0, -12), (-14, 8), (14, 8),
                                 (-14, -8), (14, -8), (-36, 0), (36, 0), (0, 20), (0, -20), (0, 32), (0, -32), (-48, 0), (48, 0)):
                    if side in "ab" and ddy and ((side == "b") != (ddy > 0)):
                        continue            # a vertical nudge moves the label away from its node only
                    if side in "rl" and ddx and ((side == "r") != (ddx > 0)):
                        continue
                    box = _box_for(x, y, lines, side, self.node, fs, lh)
                    box = (box[0] + ddx, box[1] + ddy, box[2] + ddx, box[3] + ddy, box[4], box[5] + ddx, box[6] + ddy)
                    g = self._score(box, circles, pts, placed)
                    disp = abs(ddx) + abs(ddy)
                    key = (min(g, 5.0), -rank * 40 - disp)
                    if best is None or key > best[0]:
                        best = (key, side, box, g, disp)
            _key, side, box, g, disp = best
            placed[k] = {"side": side, "box": box, "gap": g, "lines": lines, "disp": disp}
        # a label still short of room (a node where several outlines run together) looks further away, tied by a leader
        for k in list(self.nodes):
            if placed[k]["gap"] >= 5.0:
                continue
            lab = placed.pop(k)
            x, y = self.pos[k]
            best = (min(lab["gap"], 5.0), -lab["disp"], lab)
            for side in LABEL_SIDES:
                base = _box_for(x, y, lab["lines"], side, self.node, fs, lh)
                for ddx in range(-88, 89, 8):
                    for ddy in range(-64, 65, 8):
                        box = (base[0] + ddx, base[1] + ddy, base[2] + ddx, base[3] + ddy, base[4], base[5] + ddx, base[6] + ddy)
                        g = self._score(box, circles, pts, placed)
                        disp = abs(ddx) + abs(ddy)
                        cand = (min(g, 5.0), -disp)
                        if cand > best[:2]:
                            best = (cand[0], cand[1], {"side": side, "box": box, "gap": g, "lines": lab["lines"], "disp": disp})
            placed[k] = best[2]
        self.labels = placed

    def name_boxes(self):
        """Where each tool's name is drawn on hover, inside its own blob: {tool: {"x", "y", "box", "gap"}} (computed once)."""
        if hasattr(self, "_name_boxes"):
            return self._name_boxes
        out = {}
        self._name_boxes = out
        if not self.lay["fs"]:
            return out
        circles, pts = self._obstacles()
        labels = [v["box"][:4] for v in self.labels.values()]
        cell = 12.0
        grid = {}
        for p in pts:
            grid.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(p)
        reach = 14.0
        for t in self.tools:
            if not self.pieces[t]:
                continue
            blob = max((p for p in self.pieces[t]), key=lambda p: len(p[1]))[0]
            w = text_width(t, 16, True)
            outline = blob.outline(6.0)
            xs = [p[0] for p in outline]
            ys = [p[1] for p in outline]
            best = None
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            yy = y0 + 12
            while yy < y1 - 12:
                xx = x0 + w / 2 + 8
                while xx < x1 - w / 2 - 8:
                    box = (xx - w / 2, yy - 0.95 * 16, xx + w / 2, yy + 0.3 * 16)
                    if all(blob.distance(c) < -6 for c in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3]))):
                        g = reach
                        for c, r in circles:
                            g = min(g, _box_node_gap(box, c, r))
                        for lb in labels:
                            g = min(g, _box_gap(box, lb))
                        for ix in range(int((box[0] - reach) // cell), int((box[2] + reach) // cell) + 1):
                            for iy in range(int((box[1] - reach) // cell), int((box[3] + reach) // cell) + 1):
                                for p in grid.get((ix, iy), ()):
                                    g = min(g, _gap(box, p))
                        key = (min(g, reach), -yy)
                        if best is None or key > best[0]:
                            best = (key, xx, yy, box, g)
                    xx += 8
                yy += 8
            if best:
                out[t] = {"x": best[1], "y": best[2], "box": best[3], "gap": best[4]}
        return out


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


# --------------------------------------------------------------------------- capability map titles
def _map_titles(self):
    """Where the two column names go: the free spot nearest the preferred top corner with the widest clearance from
    every node, label and outline (the names are soft headings and must never be cut by a shape)."""
    wide = bool(self.lay["fs"])
    W, H = self.lay["size"]
    circles, pts = self._obstacles()
    boxes = [v["box"][:4] for v in self.labels.values()]
    specs = {"sim": (("Simulation", "per-sample models, ensembles, ODEs") if wide else ("Simulation",), "start"),
             "ai": (("AI", "tensor models, training, inference") if wide else ("AI",), "end")}
    pref = {"sim": (40, 22), "ai": (W - 12, 22)}
    fs1, fs2, lh = (15, 11.5, 18) if wide else (13, 11, 16)
    out = {}
    taken = []
    for key in ("sim", "ai"):
        lines, anchor = specs[key]
        w = max(text_width(lines[0], fs1, True), text_width(lines[1], fs2) if len(lines) > 1 else 0)
        h = fs1 * 1.25 + (lh if len(lines) > 1 else 0)
        best = None
        y = 18.0
        while y < H - h:
            x = 30.0 if anchor == "start" else W - 8.0
            while (anchor == "start" and x < W - w - 10) or (anchor == "end" and x > w + 10):
                left = x if anchor == "start" else x - w
                box = (left, y - 0.95 * fs1, left + w, y - 0.95 * fs1 + h)
                g = 12.0
                for c, r in circles:
                    g = min(g, _box_node_gap(box, c, r))
                for lb in boxes + taken:
                    g = min(g, _box_gap(box, lb))
                bl, bt, br, bb = box[0] - 12, box[1] - 12, box[2] + 12, box[3] + 12
                for p in pts:
                    if bl < p[0] < br and bt < p[1] < bb:
                        g = min(g, _gap(box, p))
                near = math.dist((x, y), pref[key])
                k = (min(g, 6.0), -near)
                if best is None or k > best[0]:
                    best = (k, x, y, box, g)
                x += 16 if anchor == "start" else -16
            y += 16
        _k, x, y, box, g = best
        taken.append(box)
        out[key] = {"x": x, "y": y, "anchor": anchor, "lines": lines, "box": box, "gap": g, "fs": (fs1, fs2), "lh": lh}
    return out


CapMap.titles = _map_titles
