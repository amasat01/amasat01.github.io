# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""One line icon per radar axis: a 24x24 grid, drawn with the current colour at one stroke width
(``ICON_STROKE``), no fill except where a shape is meant to be solid. Each value is the inner SVG
markup; ``sync_cards.py`` places it in ``<symbol>`` elements of the generated radar."""
import math

ICON_STROKE = 1.75


def _gear():
    """Eight-tooth gear outline with a hub circle."""
    pts = []
    for k in range(8):
        base = k * math.pi / 4
        for da, r in ((-0.30, 6.4), (-0.17, 9.0), (0.17, 9.0), (0.30, 6.4)):
            pts.append((12 + r * math.cos(base + da), 12 + r * math.sin(base + da)))
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
    return f'<path d="{d}"/><circle cx="12" cy="12" r="2.6"/>'


def _bez(p0, p1, p2, p3, t):
    u = 1 - t
    return tuple(u**3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t**3 * d for a, b, c, d in zip(p0, p1, p2, p3))


def _adaptive():
    """A smooth curve with solution points close together where it bends and far apart where it is flat."""
    p0, p1, p2, p3 = (3, 18), (9, 18), (9, 5), (21, 5)
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="1.5" fill="currentColor"/>' % _bez(p0, p1, p2, p3, t)
                   for t in (0.0, 0.34, 0.5, 0.66, 1.0))
    return '<path d="M3 18C9 18 9 5 21 5"/>' + dots


def _arrow(x0, y0, x1, y1, head=3.4):
    """A line with an open arrowhead at its end."""
    a = math.atan2(y1 - y0, x1 - x0)
    pts = [(x1 - head * math.cos(a + w), y1 - head * math.sin(a + w)) for w in (0.55, -0.55)]
    return (f"M{x0:.1f} {y0:.1f}L{x1:.1f} {y1:.1f}M{pts[0][0]:.1f} {pts[0][1]:.1f}L{x1:.1f} {y1:.1f}"
            f"L{pts[1][0]:.1f} {pts[1][1]:.1f}")


def _tangent():
    p0, p1, p2, p3 = (3, 20), (11, 20), (16, 15), (21, 4)
    x, y = _bez(p0, p1, p2, p3, 0.5)
    dx, dy = 3 * (p3[0] + p2[0] - p1[0] - p0[0]) / 4, 3 * (p3[1] + p2[1] - p1[1] - p0[1]) / 4   # B'(0.5) / 3 * ...
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    return (f'<path d="M3 20C11 20 16 15 21 4"/><path d="M{x - 8 * ux:.1f} {y - 8 * uy:.1f}L{x + 8 * ux:.1f} {y + 8 * uy:.1f}"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.5" fill="currentColor"/>')


ICONS = {
    # measured axes
    "uneven": '<path d="M4 6h16M4 12h8M4 18h12"/>',
    "regular": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "small": '<circle cx="12" cy="13.5" r="7"/><path d="M12 13.5V9.5M10 3h4"/>',
    "adaptive": _adaptive(),
    "compile": _gear(),
    "memory": ('<rect x="6" y="6" width="12" height="12" rx="1.5"/><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3'
               'M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3"/>'),
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14"/>',
    # rubric axes
    "tensor": ('<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12L4 7.5M12 12l8-4.5M12 12v9"/>'),
    "array_style": ('<rect x="3" y="14" width="18" height="6" rx="1"/><path d="M9 14v6M15 14v6M12 4v6M9 7h6"/>'),
    "half_precision": ('<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M12 7v10"/>'
                       '<rect x="3" y="7" width="9" height="10" rx="2" fill="currentColor"/>'),
    "control": ('<path d="M3 6h3M10 6h11M3 12h9M16 12h5M3 18h2M9 18h12"/>'
                '<circle cx="8" cy="6" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="7" cy="18" r="2"/>'),
    "single_thread": '<rect x="6.5" y="8" width="11" height="8" rx="1.5"/><path d="M12 2.5v19"/><path d="M9.8 4.7L12 2.5l2.2 2.2"/>',
    "differentiable": _tangent(),
    "arrays": '<rect x="3" y="3" width="12" height="12" rx="1.5"/><rect x="9" y="9" width="12" height="12" rx="1.5"/>',
    "deploy": '<path d="M12 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2v-6M14 4h6v6M20 4l-9 9"/>',
    "extensible": '<rect x="3" y="8" width="12" height="12" rx="1.5"/><path d="M18 3v8M14 7h8"/>',
}

#: One icon per major axis of the landing radar, reusing the minor icon that fits it best.
ICONS.update({
    "ensemble": ICONS["uneven"],
    "footprint": ICONS["memory"],
    "numerics": ICONS["tensor"],
    "authoring": ICONS["single_thread"],
    "lowlevel": ICONS["control"],
    "reach": ICONS["deploy"],
})

#: The two features behind "Batches that thin out", and one icon per block of work in the two-worlds chart: the same
#: family (24 grid, ``ICON_STROKE``, current colour). Blocks that are a feature reuse its icon above.
ICONS.update({
    "thinning": '<path d="M4 6h16M4 12h10M4 18h4"/><path d="M17 12h3M11 18h9" stroke-dasharray="1.5 2.5"/>',
    "uneven_eff": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 16V9M12 16v-5M16 16v-3"/>',
    "app-ensemble": '<circle cx="6" cy="7" r="2"/><circle cx="17" cy="6" r="2"/><circle cx="12" cy="13" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="17" r="2"/>',
    "app-divergent": '<path d="M4 6h16M4 12h7M4 18h12"/><circle cx="17" cy="12" r="2.5"/>',
    "app-diffsim": ICONS["differentiable"] + '<path d="M3 20h18" stroke-dasharray="2 2"/>',
    "app-training": '<path d="M4 6h16M4 12h16M4 18h16M8 6v12M16 6v12"/>',
    "app-inference": '<path d="M13 3L5 13h6l-1 8 8-10h-6z"/>',
    "app-datagen": '<circle cx="6" cy="7" r="2"/><circle cx="6" cy="17" r="2"/><circle cx="11" cy="12" r="2"/><path d="M14 12h7M18 9l3 3-3 3"/>',
    "app-hybrid": '<path d="M3 17C7 17 8 7 12 7s5 10 9 10"/><circle cx="6" cy="5" r="1.6"/><circle cx="18" cy="5" r="1.6"/><circle cx="12" cy="19" r="1.6"/><path d="M6 5l6 14M18 5l-6 14"/>',
    "app-handtuned": '<path d="M14 4a4 4 0 00-3.5 6L4 16.5 7.5 20l6.5-6.5A4 4 0 0020 10l-3 1-2-2 1-3z"/>',
})
