#!/usr/bin/env python3
# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Generate the landing site's card-derived MyST include files from an eagle checkout.

Usage::

    python tools/sync_cards.py <eagle-root> [--out-dir _generated]

Reads the committed performance-card JSONs (plus, for the "same task" section,
the card script that produced them, for the ``# >>> code:NAME`` ... ``# <<< code:NAME``
blocks) from an eagle checkout -- read-only, eagle is never written to -- and writes,
under ``<out-dir>`` (default ``_generated/`` at the repo root):

- ``perf_glance.md``      -- included by index.md's "Performance at a glance"
- ``same_task_short.md``  -- included by index.md's short "Same task, five ways"
- ``same_task_full.md``   -- included by where_raptor_fits.md's full version
- ``cpu_glance.md``       -- included by index.md's "On your CPU" (one tab per CPU card)
- ``SOURCES.json``        -- every source file's md5 (for drift detection) and
                             every number this run wrote onto the page (for the
                             "every number comes from a card" gate)

This script is maintenance-time only: nothing in the site's own CI invokes it
or needs eagle checked out. Re-run it by hand whenever the cards are re-run
(see the module docstring of the two card scripts for how), then diff/commit
the regenerated files. Deterministic: the same eagle-root produces byte
identical output every time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import re
import sys
import textwrap
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
SITE_ROOT = HERE.parent

# --------------------------------------------------------------------------- #
# Small formatting helpers (deliberately not imported from eagle: the site's
# generated output must not depend on eagle being importable).
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")


def _center(stat):
    """A card's wall value: the trimmed mean when present, else the median
    (copy of eagle's ``_card_common.center``; this repo cannot import eagle)."""
    return stat["mean"] if "mean" in stat else stat["median"]


def _fmt_time(seconds):
    if seconds is None:
        return "–"
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs")):
        if float(f"{seconds:.3g}") >= scale:
            return f"{seconds / scale:.3g} {unit}"
    return f"{seconds * 1e9:.3g} ns"


def _fmt_mib(nbytes):
    return "–" if nbytes is None else f"{nbytes / 2**20:.3g} MiB"


def _fmt_mib_int(nbytes):
    """GPU memory as a whole number of MiB -- the memory headline/table never
    shows a fraction (the driver itself accounts in ~2 MiB pages, so a
    fractional MiB would be false precision)."""
    return "–" if nbytes is None else f"{round(nbytes / 2**20)} MiB"


def _fmt_x(value):
    return "–" if value is None else f"{value:.3g}×"


def _fmt_sig_time(seconds, sig=3):
    """Wall/kernel time at a fixed `sig` significant figures, as a FIXED
    decimal count (unlike ``_fmt_time``'s ``%.3g``, which silently drops a
    trailing zero: 7.40 s would print as "7.4 s"). Needed wherever two
    numbers in the same table/chart must carry the same number of decimals
    to be visually comparable (the "Why RAPTOR" bars and table)."""
    if seconds is None:
        return "–"
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs")):
        v = seconds / scale
        if v >= 1:
            digits_before = max(1, math.floor(math.log10(v)) + 1)
            decimals = max(0, sig - digits_before)
            return f"{v:.{decimals}f} {unit}"
    return f"{seconds * 1e9:.{sig}g} ns"


def _md5(path):
    return hashlib.md5(pathlib.Path(path).read_bytes(), usedforsecurity=False).hexdigest()


# --------------------------------------------------------------------------- #
# Provenance: every source file read, and every number written to the page.
# --------------------------------------------------------------------------- #
class Pool:
    """Collects (a) the source files this run read, each with its md5 relative
    to the eagle-root, and (b) every numeric token written into the generated
    markdown -- so a test can check that no number on the page is un-sourced,
    and that nobody hand-edited the generated files afterwards."""

    def __init__(self, eagle_root):
        self.eagle_root = pathlib.Path(eagle_root)
        self.sources = {}   # relpath -> md5
        self.numbers = set()

    def source(self, relpath):
        p = self.eagle_root / relpath
        self.sources[str(relpath)] = _md5(p)
        return p

    def track(self, text):
        """Harvest numeric tokens from text that is about to be written to the
        page (card prose, table cells, code). Returns text unchanged."""
        for m in _NUM_RE.finditer(text):
            self.numbers.add(m.group(0))
        return text

    def as_json(self):
        return {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": [{"path": k, "md5": v} for k, v in sorted(self.sources.items())],
            "numbers": sorted(self.numbers),
        }


class Writer:
    """Accumulates generated markdown lines, tracking every number through
    the shared Pool as they are added."""

    def __init__(self, pool):
        self.pool = pool
        self.lines = []

    def add(self, line=""):
        self.pool.track(line)
        self.lines.append(line)
        return self

    def extend(self, lines):
        for line in lines:
            self.add(line)
        return self

    def text(self):
        return "\n".join(self.lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# Card loading and schema adapters (perf_card/cpu_card use "code"; rk78_card
# uses "code_lines"; cpu_card's "arms" is a list with a separate "arm_labels",
# the others' "arms" is a {key: label} dict).
# --------------------------------------------------------------------------- #
def load_card(pool, relpath):
    path = pool.source(relpath)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


#: The device every family's reference card is read from, by slug
#: (``device_slug``/``cpu_slug``, or the slug the filename itself carries --
#: see ``card_slug`` below). Picking this by slug, not by sorting
#: ``card_*.json`` alphabetically, is what keeps the reference device chosen
#: here from flipping to whichever device's card sorts first once a second
#: one is committed (e.g. a Kaggle Tesla T4 next to the Quadro P2000).
REFERENCE_SLUGS = {
    "perf_gpu": "quadro-p2000",
    "perf_cpu": "intel-xeon-w-2125",
    "rk78_gpu": "quadro-p2000",
    "rk78_cpu": "intel-r-xeon-r-w-2125-cpu-4-00ghz",
}

#: (directory, filename prefix) under the eagle root, by family key.
FAMILY_DIRS = {
    "perf_gpu": ("benchmarks/perf_card", "card_"),
    "perf_cpu": ("benchmarks/perf_card", "cpu_card_"),
    "rk78_gpu": ("benchmarks/rk78_card", "card_"),
    "rk78_cpu": ("benchmarks/rk78_card", "cpu_card_"),
}

#: eagle docs anchors are ``{family}-{slug}`` where ``{family}`` is
#: ``gen_perf_pages.py``'s key, not this script's -- the two were named
#: independently and happen to differ for the RK4 families.
EAGLE_ANCHOR_FAMILY = {
    "perf_gpu": "perf_card_gpu", "perf_cpu": "perf_card_cpu",
    "rk78_gpu": "rk78_card_gpu", "rk78_cpu": "rk78_card_cpu",
}
FAMILY_TITLES = {
    "perf_gpu": "RK4 oscillators, GPU", "perf_cpu": "RK4 oscillators, CPU",
    "rk78_gpu": "RK7(8) orbits, GPU", "rk78_cpu": "RK7(8) orbits, CPU",
}


def card_slug(card, path, prefix):
    return card.get("device_slug") or card.get("cpu_slug") or path.stem[len(prefix):]


def family_cards(pool, eagle_root, reldir, prefix):
    """[(slug, card), ...] for every card under ``reldir`` matching
    ``prefix``, in filename order (deterministic, but never itself the basis
    for which one is "the" reference -- see `reference_card`)."""
    d = pathlib.Path(eagle_root) / reldir
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob(f"{prefix}*.json")):
        card = load_card(pool, p.relative_to(eagle_root))
        if card is not None:
            out.append((card_slug(card, p, prefix), card))
    return out


def reference_card(entries, reference_slug):
    """The entry whose slug is ``reference_slug``; if none matches (a
    fixture, or a dev tree that has not named its one device that way), the
    first by filename order, so a single-device tree still works."""
    for slug, card in entries:
        if slug == reference_slug:
            return card
    return entries[0][1] if entries else None


def device_name(card):
    if card.get("device"):
        return card["device"]["name"]
    cpu = card.get("cpu")
    if isinstance(cpu, dict):
        return cpu.get("model", "device")
    return cpu if isinstance(cpu, str) else "device"


def arm_label(card, arm):
    arms = card["arms"]
    if isinstance(arms, dict):
        return arms.get(arm, arm)
    return card.get("arm_labels", {}).get(arm, arm)


def arm_keys(card):
    arms = card["arms"]
    return list(arms.keys()) if isinstance(arms, dict) else list(arms)


def device_label(card):
    if card.get("device"):
        d = card["device"]
        return f"{d['name']} (compute capability {d['compute_capability']}, {d['sm_count']} SMs)"
    if card.get("cpu"):
        c = card["cpu"]
        return f"{c['model']} ({c['cores']} cores, {c['logical_cpus']} logical CPUs)"
    return "the card's own device"


def arm_blocks_map(card):
    """{arm: [block name, ...]} in order, whichever schema this card uses."""
    if "code" in card:
        return {a: v["blocks"] for a, v in card["code"]["arms"].items()}
    if "code_lines" in card:
        return card["code_lines"]["arm_blocks"]
    return {}


def arm_line_count(card, arm):
    if "code" in card:
        return card["code"]["arms"].get(arm, {}).get("lines")
    if "code_lines" in card:
        return card["code_lines"]["arms"].get(arm)
    return None


# --------------------------------------------------------------------------- #
# Card script parsing: the `# >>> code:NAME` ... `# <<< code:NAME` blocks.
# --------------------------------------------------------------------------- #
def code_blocks(script_text):
    """{name: raw source text (dedented)} for every marked block in a card
    script. Mirrors the parsing each card script does on itself."""
    blocks, open_name, buf = {}, None, []
    for line in script_text.splitlines():
        s = line.strip()
        if s.startswith("# >>> code:"):
            open_name, buf = s.split(":", 1)[1].strip(), []
        elif s.startswith("# <<< code:"):
            name = s.split(":", 1)[1].strip()
            assert open_name == name, f"unbalanced code marker: {s}"
            blocks[open_name] = textwrap.dedent("\n".join(buf)).strip("\n")
            open_name = None
        elif open_name is not None:
            buf.append(line)
    assert open_name is None, f"unclosed code block: {open_name}"
    return blocks


def arm_source(blocks, names):
    parts = []
    for name in names:
        if name in blocks:
            parts.append(blocks[name])
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# "Performance at a glance" -- one compact table per card.
# --------------------------------------------------------------------------- #
def glance_table(pool, w, card, title):
    ns = card.get("ns") or []
    if not ns or not card.get("results"):
        return False
    n = max(ns)
    configs = card.get("configs") or []
    results_by_cell = {}
    for r in card["results"]:
        if r["n"] != n:
            continue
        key = (r.get("distribution"), r.get("max_steps"))
        results_by_cell.setdefault(key, []).append(r)
    # memory/compile lookups, tolerant of either card's field names
    mem_by_key = {}
    for row in (card.get("memory") or {}).get("rows", []):
        key = (row.get("n"), row.get("distribution"), row.get("max_steps"), row["arm"])
        mem_by_key[key] = row
    compile_by_arm = {}
    for row in (card.get("compile_time") or {}).get("rows", []):
        arms = row.get("arms") or ([row["arm"]] if "arm" in row else [])
        for a in arms:
            compile_by_arm[a] = row

    device = device_label(card)
    problem = card["workload"]["problem"]
    w.add(f"**{title}.** {pool.track(problem)}. Device: {pool.track(device)}. "
          f"Largest batch shown: N = {n:,}.")
    w.add("")
    w.add("| workload | arm | wall | × fastest hawk + eagle arm | memory | compile (cold / warm) |")
    w.add("|---|---|---:|---:|---:|---:|")
    for cfg in configs or [{"distribution": None, "max_steps": None}]:
        dist, steps = cfg.get("distribution"), cfg.get("max_steps")
        cell = results_by_cell.get((dist, steps), [])
        if not cell:
            continue
        eagle_rows = [r for r in cell if r["arm"].startswith("eagle")]
        fastest_eagle = min((_center(r["wall_s"]) for r in eagle_rows), default=None)
        workload = f"spread S={steps}" if dist == "spread" else (
            f"uniform S={steps}" if dist == "uniform" else "(single configuration)")
        for r in sorted(cell, key=lambda r: _center(r["wall_s"])):
            arm = r["arm"]
            wall = _center(r["wall_s"])
            ratio = _fmt_x(wall / fastest_eagle) if fastest_eagle else "–"
            mrow = mem_by_key.get((n, dist, steps, arm))
            mem = _fmt_mib((mrow or {}).get("device_peak_bytes", (mrow or {}).get("peak_bytes")))
            crow = compile_by_arm.get(arm)
            compile_cell = (f"{_fmt_time(crow['cold_s']['median'])} / "
                             f"{_fmt_time(crow['warm_s']['median'])}") if crow else "–"
            w.add(f"| {pool.track(workload)} | {arm_label(card, arm)} "
                  f"| {pool.track(_fmt_time(wall))} | {pool.track(ratio)} "
                  f"| {pool.track(mem)} | {pool.track(compile_cell)} |")
    w.add("")
    return True


def build_measured_on(pool, w, all_cards):
    """Every device of every family, linked to its eagle docs anchor -- so a
    new card (a new device, in any of the four families) shows up here with
    no further edit to this script's output or to this site's pages."""
    base = "https://amasat01.github.io/eagle/content/performance.html"
    rows = [(key, slug, card) for key in FAMILY_TITLES
            for slug, card in all_cards.get(key, [])]
    if not rows:
        return False
    w.add("**Measured on:**")
    w.add("")
    for key, slug, card in rows:
        # Sphinx/docutils normalizes a MyST target label's underscores to
        # hyphens in the built page's HTML id; this literal external link
        # (unlike an in-build MyST cross-reference) is never rewritten for
        # it, so it must already spell the normalized, hyphenated form.
        anchor = f"{EAGLE_ANCHOR_FAMILY[key]}-{slug}".replace("_", "-")
        w.add(f"- {pool.track(FAMILY_TITLES[key])}: "
              f"[{pool.track(device_name(card))}]({base}#{anchor})")
    w.add("")
    return True


def build_perf_glance(pool, perf_gpu, perf_cpu, all_cards):
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    any_card = False
    if perf_gpu:
        any_card |= glance_table(pool, w, perf_gpu,
                                  "RK4 oscillators, GPU")
    if perf_cpu:
        any_card |= glance_table(pool, w, perf_cpu,
                                  "RK4 oscillators, CPU")
    build_measured_on(pool, w, all_cards)
    link = "https://amasat01.github.io/eagle/content/performance.html"
    w.add(f"Full cards, every workload and column: [eagle's performance page]({link}).")
    return w.text(), any_card


# --------------------------------------------------------------------------- #
# "On your CPU" -- one block per CPU card of the perf_cpu family.
# --------------------------------------------------------------------------- #
#: The tools charted on the landing page, in display order, with the plain
#: tool name each bar carries. The other arms (one thread, multiprocessing,
#: compaction, ...) live on eagle's full card, not here.
CPU_CHART_ARMS = (("eagle_term8", "eagle, 8 threads"), ("numba_prange", "Numba"),
                  ("jax_shard8", "JAX"), ("torch_masked", "PyTorch"),
                  ("numpy_masked", "NumPy"))
#: The configuration charted: the GPU chart's own (spread, S=1000).
CPU_CHART_CONFIG = {"distribution": "spread", "max_steps": 1000}
CPU_CHIP_VAR = {"eagle_term8": "--mark-eagle", "numba_prange": "--tool-numba",
                "jax_shard8": "--tool-jax", "torch_masked": "--tool-pytorch",
                "numpy_masked": "--tool-numpy"}
EAGLE_PERF_PAGE = "https://amasat01.github.io/eagle/content/performance.html"


def cpu_tab_label(card):
    """The CPU's name without trademark marks or the "CPU @ clock" tail."""
    model = (card.get("cpu") or {}).get("model") or device_name(card)
    for mark in ("(R)", "(TM)", "(tm)"):
        model = model.replace(mark, "")
    return " ".join(re.sub(r"\s+CPU\s*@.*\Z", "", model).split())


def _cpu_row(card, arm, n):
    for r in card.get("results") or []:
        if (r["arm"] == arm and r["n"] == n
                and r.get("distribution") == CPU_CHART_CONFIG["distribution"]
                and r.get("max_steps") == CPU_CHART_CONFIG["max_steps"]):
            return r
    return None


def cpu_glance_block(pool, w, slug, card):
    """One CPU's wall-time bars (log scale, the GPU chart's markup) at the
    card's largest N. False (nothing written) when eagle's row is missing."""
    if not card.get("ns") or not card.get("results"):
        return False
    n = max(card["ns"])
    bars = []
    for arm, label in CPU_CHART_ARMS:
        r = _cpu_row(card, arm, n)
        if r is not None:
            bars.append((arm, label, _center(r["wall_s"])))
    if not bars or bars[0][0] != "eagle_term8":
        return False
    lo = min(b[2] for b in bars) / 1.6
    hi = max(b[2] for b in bars) * 1.6
    aria = ", ".join(f"{label} {_fmt_sig_time(wall)}" for _arm, label, wall in bars)
    w.add("```{raw} html")
    w.add(f'<div class="chart" role="img" aria-label="Wall time on the CPU: {aria}.">')
    for arm, label, wall in bars:
        pct = 100 * (math.log10(wall) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        w.add(_bar_row_html(pool.track(label), CPU_CHIP_VAR.get(arm), pct,
                            pool.track(_fmt_sig_time(wall)), arm.startswith("eagle")))
    w.add("</div>")
    cpu = card.get("cpu") or {}
    where = cpu_tab_label(card)
    if cpu.get("cores") and cpu.get("logical_cpus"):
        where += f" ({cpu['cores']} cores, {cpu['logical_cpus']} logical CPUs)"
    date = f", card of {card['generated_utc'][:10]}" if card.get("generated_utc") else ""
    anchor = f"{EAGLE_ANCHOR_FAMILY['perf_cpu']}-{slug}".replace("_", "-")
    w.add(f'<p class="axis-note">{pool.track(f"{n:,}")} samples, each stopping at its own step '
          f'(up to {CPU_CHART_CONFIG["max_steps"]:,}). Log scale, from {pool.track(_fmt_time(lo))} '
          f'to {pool.track(_fmt_time(hi))}. Measured on {pool.track(where)}{pool.track(date)}. '
          f'<a href="{EAGLE_PERF_PAGE}#{anchor}">Every tool, every N, and where each one fits</a>.</p>')
    w.add("```")
    w.add("")
    return True


def build_cpu_glance(pool, cpu_entries):
    """``cpu_entries``: [(slug, card), ...]. One tab per CPU (one tab for one
    CPU, so the layout does not change when a second card lands)."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    any_block = False
    blocks = []
    for slug, card in cpu_entries:
        bw = Writer(pool)
        if cpu_glance_block(pool, bw, slug, card):
            blocks.append((card, bw.text().rstrip("\n").splitlines()))
    if blocks:
        any_block = True
        w.add("::::{tab-set}")
        for card, lines in blocks:
            w.add(f":::{{tab-item}} {cpu_tab_label(card)}")
            w.add("")
            for line in lines:
                w.lines.append(line)   # already tracked by the block writer
            w.add("")
            w.add(":::")
        w.add("::::")
    else:
        w.add("No CPU card found under the given eagle root yet.")
    return w.text(), any_block


# --------------------------------------------------------------------------- #
# "Same task, five ways" -- the RK7(8) card's code, side by side.
# --------------------------------------------------------------------------- #
PRIMARY_ARMS = [
    ("eagle_graph", "hawk + eagle"),
    ("cupy_masked", "CuPy"),
    ("torch_masked", "PyTorch"),
    ("jax_vmap", "JAX"),
    ("warp_kernel", "Warp"),
]

# What a user gets "for free" from the same source, without extra work --
# facts about each framework already stated elsewhere on this site (see
# where_raptor_fits.md), not claims introduced here.
FREE_NOTES = {
    "eagle_graph": "a CPU build from the same hawk kernel, with no second "
                   "implementation to maintain, and the kernel's own reverse- "
                   "and forward-mode derivatives.",
    "cupy_masked": "no second build and no gradient in this comparison; CuPy "
                   "itself targets the GPU.",
    "torch_masked": "gradients through `torch.autograd`, and the tensors run "
                     "on CPU too (untested on this card).",
    "jax_vmap": "gradients through `jax.grad`, and the same code runs on a CPU "
                "backend (untested on this card).",
    "warp_kernel": "reverse-mode gradients through `wp.Tape`, and a CPU device "
                   "(untested on this card).",
}


def five_ways_tabs(pool, card, script_text, source_label):
    blocks = code_blocks(script_text)
    arm_blocks = arm_blocks_map(card)
    fit = (card.get("fit") or {}).get("arms", {})
    n = max(card.get("ns") or [0])
    tabs = []
    for arm, tool in PRIMARY_ARMS:
        if arm not in arm_blocks:
            continue
        names = arm_blocks[arm]
        snippet = arm_source(blocks, names)
        lines = arm_line_count(card, arm)
        fit_line = fit.get(arm, "")
        tabs.append({
            "arm": arm, "tool": tool, "label": arm_label(card, arm),
            "snippet": snippet, "lines": lines, "fit": fit_line,
            "free": FREE_NOTES.get(arm, ""),
        })
    return tabs, n


def render_fact_table(pool, w, t):
    w.add("| fact | |")
    w.add("|---|---|")
    w.add(f"| lines (non-blank, non-comment) | {pool.track(str(t['lines']))} |")
    w.add(f"| what it brings here | {pool.track(t['fit'])} |")
    w.add(f"| free from the same source | {pool.track(t['free'])} |")
    w.add("")


def build_same_task(pool, card, script_text, source_label, full):
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    tabs, n = five_ways_tabs(pool, card, script_text, source_label)
    if not tabs:
        return w.text(), False
    problem = card["workload"]["problem"]
    w.add(f"Same task, five ways, measured by {pool.track(source_label)}: "
          f"{pool.track(problem)} Largest batch shown: N = {n:,}.")
    w.add("")
    if full:
        w.add("::::{tab-set}")
        for t in tabs:
            w.add(f":::{{tab-item}} {t['tool']}")
            render_fact_table(pool, w, t)
            w.add("```python")
            w.add(pool.track(t["snippet"]))
            w.add("```")
            w.add(":::")
        w.add("::::")
    else:
        # Short version for index.md: no tabs, one line per tool, pointing at
        # the full version.
        w.add("| tool | lines | what it brings here |")
        w.add("|---|---:|---|")
        for t in tabs:
            w.add(f"| {t['tool']} | {pool.track(str(t['lines']))} | {pool.track(t['fit'])} |")
        w.add("")
        w.add("Full code for all five, side by side: "
              "[where RAPTOR fits](where_raptor_fits.md).")
    return w.text(), True


# --------------------------------------------------------------------------- #
# "Why RAPTOR" comparison excerpt (index.md, right below the hero) and the
# fuller "fastest arm" summary further down -- both derived straight from the
# reference GPU card, nothing hand-typed. `compare.md`'s per-question content
# reuses the same helpers.
# --------------------------------------------------------------------------- #
#: The five arms the hero chart/table shows, at the configuration that reads
#: as "my samples finish at different times" (spread stop steps, up to 1000).
WHY_ARMS = ("eagle_simulate", "warp_kernel", "jax_vmap", "cupy_masked", "torch_masked")
WHY_CONFIG = {"distribution": "spread", "max_steps": 1000}
#: "my batch is dense": every sample runs the full step count.
DENSE_CONFIG = {"distribution": "uniform", "max_steps": 1000}

#: The four "other guys in the room" the hero/why-raptor comparison names
#: ("name the other guys, like faster than x, y, z" was the goal),
#: in the order they are always quoted -- never resorted by ratio. Brand
#: names, deliberately not the card's own `arm_label` (e.g. "Warp per-thread
#: kernel" describes the implementation strategy; this caption names the
#: tool).
COMPARISON_ARMS = ("warp_kernel", "jax_vmap", "cupy_masked", "torch_masked")
COMPARISON_TOOL_NAMES = {
    "warp_kernel": "NVIDIA Warp", "jax_vmap": "JAX",
    "cupy_masked": "CuPy", "torch_masked": "PyTorch",
}


def _round_sig_floor(value, sig=2):
    """`value` rounded to `sig` significant figures, truncated towards zero
    -- a displayed speed-up must never overstate the true margin (never
    "invent, round up or strengthen a number"). `None`/non-positive in,
    `None` out.

    The final `round(..., decimals)` is not cosmetic: `count * quantum`
    alone (e.g. ``34 * 0.1``) lands on whichever double is nearest to
    3.4000000000000004, a different float object than the literal ``3.4``
    -- two independently-floored ratios that are the SAME display value
    (e.g. cupy/torch both floor to 41x) must compare equal with ``==`` for
    `named_speedup_caption`'s grouping, which the un-rounded product is not
    guaranteed to do."""
    if value is None or value <= 0:
        return None
    exp = math.floor(math.log10(value))
    quantum = 10.0 ** (exp - sig + 1)
    # the 1e-9 guard absorbs float noise from the division itself landing a
    # hair under an exact multiple of `quantum` (e.g. 9.999999999999998),
    # which would otherwise floor one quantum too low -- it is far smaller
    # than anything `sig` significant figures could ever resolve.
    count = math.floor(value / quantum + 1e-9)
    decimals = max(0, sig - 1 - exp)
    return round(count * quantum, decimals)


def _fmt_ratio(value, sig=2):
    """An already-floored ratio as "4.0×" / "41×" -- fixed `sig` significant
    figures as a FIXED decimal count, matching `_fmt_sig_time`'s contract."""
    if value is None:
        return "–"
    exp = math.floor(math.log10(value)) if value > 0 else 0
    decimals = max(0, sig - 1 - exp)
    return f"{value:.{decimals}f}×"


def _mem_row(card, arm, n, config=WHY_CONFIG):
    """The one `memory.rows` entry for `arm` at (`n`, `config`), or None --
    the memory-table analogue of `_cell`/`_by_arm` above, one arm at a time
    since every call site below already knows which arm it wants."""
    for row in (card.get("memory") or {}).get("rows", []):
        if (row.get("arm") == arm and row.get("n") == n
                and row.get("distribution") == config["distribution"]
                and row.get("max_steps") == config["max_steps"]):
            return row
    return None


#: The two "heavier" tools the memory headline names, CuPy then PyTorch --
#: same order every time (never resorted by ratio), mirroring
#: `COMPARISON_ARMS`'s contract one level down (bytes, not wall time).
MEMORY_COMPARISON_ARMS = ("cupy_masked", "torch_masked")


def memory_savings(card, base_arm="eagle_simulate", arms=MEMORY_COMPARISON_ARMS, config=WHY_CONFIG):
    """(n, [(arm, floored_ratio), ...]) -- `arms`' `device_peak_bytes` over
    `base_arm`'s, at the card's largest N and `config`, each ratio floored to
    2 significant figures (never overstate a saving). ``(None, [])`` if the
    cell or `base_arm` itself is missing -- mirrors `named_speedup` exactly."""
    if not card or not card.get("ns"):
        return None, []
    n = max(card["ns"])
    base = _mem_row(card, base_arm, n, config)
    if not base or not base.get("device_peak_bytes"):
        return n, []
    base_bytes = base["device_peak_bytes"]
    pairs = []
    for arm in arms:
        row = _mem_row(card, arm, n, config)
        if not row or not row.get("device_peak_bytes"):
            continue
        pairs.append((arm, _round_sig_floor(row["device_peak_bytes"] / base_bytes)))
    return n, pairs


def memory_savings_big_text(pairs):
    """"2.6×–3.5× less GPU memory" -- the smallest and largest floored ratio
    among `pairs`. ``None`` if `pairs` is empty."""
    ratios = [r for _arm, r in pairs if r is not None]
    if not ratios:
        return None
    lo, hi = min(ratios), max(ratios)
    if lo == hi:
        return f"{_fmt_ratio(lo)} less GPU memory"
    return f"{_fmt_ratio(lo)}–{_fmt_ratio(hi)} less GPU memory"


def _n_words(n):
    """"a million" for exactly 1,000,000 -- the one catchy phrasing the
    memory headline asked for; any other N falls back to a plain
    thousands-grouped count, so a future card re-run at a different N never
    prints nonsense."""
    return "a million" if n == 1_000_000 else f"{n:,}"


#: The arms the "Will it fit on my GPU?" table shows, same cell as the speed
#: strip/chart (`WHY_CONFIG`) -- `eagle_graph` stands in for "eagle without
#: compaction" (the honest box's own phrase for it).
MEMORY_TABLE_ARMS = ("eagle_simulate", "eagle_graph", "warp_kernel", "jax_vmap",
                     "cupy_masked", "torch_masked")
MEMORY_TABLE_LABELS = {
    "eagle_simulate": "eagle.simulate", "eagle_graph": "hawk + eagle graph (no compaction)",
    "warp_kernel": "NVIDIA Warp", "jax_vmap": "JAX",
    "cupy_masked": "CuPy", "torch_masked": "PyTorch",
}


def will_it_fit_rows(card, arms=MEMORY_TABLE_ARMS, config=WHY_CONFIG):
    """[(arm, device_peak_bytes, device_factor), ...] for every `arms` entry
    the card ran at its largest N and `config`, lightest first."""
    if not card or not card.get("ns"):
        return [], None
    n = max(card["ns"])
    rows = []
    for arm in arms:
        row = _mem_row(card, arm, n, config)
        if row and row.get("device_peak_bytes") is not None:
            rows.append((arm, row["device_peak_bytes"], row.get("device_factor")))
    rows.sort(key=lambda r: r[1])
    return rows, n


def named_speedup(card, base_arm="eagle_simulate", arms=COMPARISON_ARMS, config=WHY_CONFIG):
    """(n, [(arm, floored_ratio), ...]) -- `base_arm`'s speed-up over each of
    `arms` that ran this cell, at the card's largest N and `config`, each
    ratio floored to 2 significant figures. `arms`' order is preserved (the
    caption is never resorted by ratio). ``(None, [])`` if the cell or
    `base_arm` itself is missing."""
    if not card or not card.get("ns"):
        return None, []
    n = max(card["ns"])
    rows = _by_arm(_cell(card, n, config))
    base = rows.get(base_arm)
    if not base:
        return n, []
    base_s = _center(base["wall_s"])
    pairs = []
    for arm in arms:
        r = rows.get(arm)
        if not r:
            continue
        pairs.append((arm, _round_sig_floor(_center(r["wall_s"]) / base_s)))
    return n, pairs


def named_speedup_big_text(pairs):
    """"3.4×–41× faster" -- the smallest and largest floored ratio among
    `pairs`. ``None`` if `pairs` is empty."""
    ratios = [r for _arm, r in pairs if r is not None]
    if not ratios:
        return None
    lo, hi = min(ratios), max(ratios)
    if lo == hi:
        return f"{_fmt_ratio(lo)} faster"
    return f"{_fmt_ratio(lo)}–{_fmt_ratio(hi)} faster"


def named_speedup_caption(pairs):
    """"NVIDIA Warp (3.4×), JAX (7.4×), CuPy and PyTorch (41×)" -- arms that
    land on the same floored ratio, ADJACENT in `pairs`' own order, are
    grouped under one parenthesis joined by "and"; the groups themselves are
    always comma-joined (never a trailing Oxford "and" between groups -- a
    merged group already reads as one item)."""
    groups = []
    for arm, ratio in pairs:
        if ratio is None:
            continue
        name = COMPARISON_TOOL_NAMES.get(arm, arm)
        if groups and groups[-1][0] == ratio:
            groups[-1][1].append(name)
        else:
            groups.append((ratio, [name]))
    return ", ".join(f"{' and '.join(names)} ({_fmt_ratio(ratio)})" for ratio, names in groups)


def _cell(card, n, cfg):
    return [r for r in card.get("results", [])
            if r["n"] == n and r.get("distribution") == cfg["distribution"]
            and r.get("max_steps") == cfg["max_steps"]]


def _by_arm(rows):
    return {r["arm"]: r for r in rows}


def why_raptor_bars(card, config=WHY_CONFIG, arms=WHY_ARMS):
    """[(arm, label, wall_s), ...] sorted fastest first -- only the arms in
    `arms` the card actually ran, at its largest N and `config`."""
    if not card or not card.get("ns"):
        return [], None
    n = max(card["ns"])
    rows = _by_arm(_cell(card, n, config))
    bars = [(arm, arm_label(card, arm), _center(rows[arm]["wall_s"]))
            for arm in arms if arm in rows]
    bars.sort(key=lambda b: b[2])
    return bars, n


def fastest_of_cell(card, n, config):
    """(how many arms ran this N/config, the fastest (arm, row)) or None."""
    rows = _cell(card, n, config)
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: _center(r["wall_s"]))
    return len(rows), rows[0]


def simulate_vs_twin_kernel_pct(card, simulate="eagle_simulate", twin="eagle_graph_auto"):
    """Max absolute %% deviation of `simulate`'s KERNEL-only time from its
    hand-built twin's, over every cell both ran. Kernel time, not wall: at
    small N wall is dominated by Python/launch overhead both arms pay
    identically, which is noise, not a real difference between the two."""
    sim, twin_rows = {}, {}
    for r in card.get("results", []):
        key = (r.get("distribution"), r.get("max_steps"), r["n"])
        if r["arm"] == simulate:
            sim[key] = r
        elif r["arm"] == twin:
            twin_rows[key] = r
    deviations = []
    for key, r in sim.items():
        t = twin_rows.get(key)
        if not t or not r.get("kernel_only_s") or not t.get("kernel_only_s"):
            continue
        deviations.append(abs(r["kernel_only_s"] / t["kernel_only_s"] - 1) * 100)
    return max(deviations) if deviations else None


def dense_tie_line(card, config=DENSE_CONFIG):
    """The honest 'ties dense batches' callout: Warp vs the fastest `eagle*`
    arm at the dense config, largest N. {"verdict": "a tie"} when within 3%;
    otherwise whichever genuinely won, so this never overclaims if a future
    card re-run moves the numbers apart."""
    if not card or not card.get("ns"):
        return None
    n = max(card["ns"])
    rows = _by_arm(_cell(card, n, config))
    warp = rows.get("warp_kernel")
    eagle_candidates = [(a, r) for a, r in rows.items() if a.startswith("eagle")]
    if not warp or not eagle_candidates:
        return None
    eagle_arm, eagle_row = min(eagle_candidates, key=lambda ar: _center(ar[1]["wall_s"]))
    w, e = _center(warp["wall_s"]), _center(eagle_row["wall_s"])
    # "tie" (noun) / "warp" / "eagle" (which one actually won) -- each call
    # site below phrases this in its own grammar; never a shared adjective.
    verdict = "tie" if 0.97 <= e / w <= 1.03 else ("eagle" if e < w else "warp")
    return {"n": n, "warp_s": w, "eagle_arm": eagle_arm,
            "eagle_label": arm_label(card, eagle_arm), "eagle_s": e, "verdict": verdict}


#: The non-eagle arms the RK7(8) honesty line names, in the order quoted.
RK78_HONEST_ARMS = ("warp_kernel", "jax_vmap", "cupy_masked", "torch_masked")


def rk78_honest(card):
    """The RK7(8)-family honesty line: the fastest GPU `eagle*` arm (never
    `eagle_simulate`/`eagle_cpu` -- the hand-tuned graph variants are the
    point here), the same handful of other tools, and whether eagle's
    CPU-only arm actually beats every GPU arm on this card (it does on a
    FP64-weak development GPU -- worth knowing, so this is computed, never
    assumed)."""
    if not card or not card.get("ns"):
        return None
    n = max(card["ns"])
    rows = _by_arm([r for r in card.get("results", []) if r["n"] == n])
    eagle_candidates = [(a, r) for a, r in rows.items()
                        if a.startswith("eagle") and a not in ("eagle_simulate", "eagle_cpu")]
    if not eagle_candidates:
        return None
    fastest_arm, fastest_row = min(eagle_candidates, key=lambda ar: _center(ar[1]["wall_s"]))
    others = [(arm_label(card, a), _center(rows[a]["wall_s"]))
              for a in RK78_HONEST_ARMS if a in rows]
    cpu_row = rows.get("eagle_cpu")
    fastest_s = _center(fastest_row["wall_s"])
    # "beats every GPU arm" must mean every GPU arm actually on the card,
    # not just the fastest `eagle*` one -- Warp, JAX etc. could in principle
    # be faster than eagle's own graph while still losing to the CPU arm.
    gpu_min = min((_center(r["wall_s"]) for a, r in rows.items() if a != "eagle_cpu"),
                  default=None)
    return {
        "n": n, "fastest_label": arm_label(card, fastest_arm), "fastest_s": fastest_s,
        "others": others,
        "cpu_label": arm_label(card, "eagle_cpu") if cpu_row else None,
        "cpu_s": _center(cpu_row["wall_s"]) if cpu_row else None,
        "cpu_beats_every_gpu_arm": bool(cpu_row) and gpu_min is not None
                                    and _center(cpu_row["wall_s"]) < gpu_min,
    }


def warp_wins_count(card):
    """(cells warp_kernel wins outright, total cells) over every
    configuration x N the card runs -- "fastest in 7 of 12" is this, not a
    hardcoded count, so it moves if a future re-run changes the standings."""
    if not card or not card.get("ns") or not card.get("configs"):
        return None
    wins, total = 0, 0
    for cfg in card["configs"]:
        for n in card["ns"]:
            found = fastest_of_cell(card, n, cfg)
            if not found:
                continue
            total += 1
            if found[1]["arm"] == "warp_kernel":
                wins += 1
    return (wins, total) if total else None


def memory_comparison_sentence(pool, sim_mem, warp_mem, graph_mem):
    """The one memory-honesty sentence both pages use, ordered by the
    card's own device_factor values: whichever of eagle.simulate and NVIDIA
    Warp is lighter is named lighter, and "lighter still" is claimed for
    hawk + eagle's lower-level, uncompacted arm only when it really is below
    both. Arguments are card memory rows (or None for a missing arm)."""
    s = sim_mem["device_factor"]
    wv = warp_mem["device_factor"]
    g = graph_mem["device_factor"]
    fs = pool.track(_fmt_ratio(s))
    fw = pool.track(_fmt_ratio(wv))
    fg = pool.track(_fmt_ratio(g))
    if wv < s:
        head = f"NVIDIA Warp is lighter than eagle.simulate ({fw})"
    elif s < wv:
        head = f"eagle.simulate ({fs}) is lighter than NVIDIA Warp ({fw})"
    else:
        head = f"eagle.simulate and NVIDIA Warp use the same amount ({fs})"
    if g < min(s, wv):
        head += (", and hawk + eagle's lower-level building blocks, without compaction, "
                 f"are lighter still ({fg})")
    return head + "."


def build_honest_box(pool, perf_gpu):
    """``_generated/honest_box.md``: the one-line (well, up to 3 sentences)
    honest callout right under the hero strip -- device + Warp's standing,
    `eagle.simulate` vs. its hand-tuned twin, and the same honesty one level
    down for memory (whichever of Warp and eagle.simulate the card shows
    lighter, and eagle's own lower-level, uncompacted arm lighter still only
    when it is), all computed."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    wins = warp_wins_count(perf_gpu)
    tie = dense_tie_line(perf_gpu)
    if not wins:
        return w.text(), False
    device = device_name(perf_gpu)
    line = (f"Measured on {pool.track(device)}, a development GPU. NVIDIA Warp's "
            f"per-thread kernel is the fastest arm in {pool.track(str(wins[0]))} of the "
            f"{pool.track(str(wins[1]))} RK4 cells this card runs")
    if tie and tie["verdict"] == "tie":
        tie_n_str = f"{tie['n']:,}"
        line += f", and ties hawk + eagle on the densest batch (N = {pool.track(tie_n_str)})."
    else:
        line += "."
    w.add(line)

    n = max(perf_gpu["ns"])
    pct = simulate_vs_twin_kernel_pct(perf_gpu)
    warp_mem = _mem_row(perf_gpu, "warp_kernel", n, WHY_CONFIG)
    graph_mem = _mem_row(perf_gpu, "eagle_graph", n, WHY_CONFIG)
    sim_mem = _mem_row(perf_gpu, "eagle_simulate", n, WHY_CONFIG)
    if pct is not None and warp_mem and graph_mem and sim_mem:
        within = math.ceil(pct)
        w.add(f"`eagle.simulate`'s GPU time is within {pool.track(str(within))}% of the "
              "hand-tuned version, in every configuration this card runs; "
              + memory_comparison_sentence(pool, sim_mem, warp_mem, graph_mem))
    return w.text(), True


def build_hero_strip(pool, perf_gpu):
    """``_generated/hero_strip.md``: the landing hero's number strip (179 ms
    / "3.4×-41× faster" named comparison / within 1%, today), as a complete,
    self-contained ``{grid}`` block -- {include}-d as-is on index.md, never
    wrapped in another ``{grid}`` there (MyST's ``{include}`` does not
    reliably nest a directive's children across the file boundary, so the
    grid owns its own fences here instead), so none of these numbers is ever
    hand-typed on the page."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    n = max(perf_gpu["ns"])
    found = fastest_of_cell(perf_gpu, n, WHY_CONFIG)
    _speedup_n, speedup_pairs = named_speedup(perf_gpu)
    big_text = named_speedup_big_text(speedup_pairs)
    _mem_n, mem_pairs = memory_savings(perf_gpu)
    mem_big_text = memory_savings_big_text(mem_pairs)
    eagle_mem = _mem_row(perf_gpu, "eagle_simulate", n, WHY_CONFIG)
    cupy_mem = _mem_row(perf_gpu, "cupy_masked", n, WHY_CONFIG)
    torch_mem = _mem_row(perf_gpu, "torch_masked", n, WHY_CONFIG)
    if (not found or not big_text or not mem_big_text
            or not eagle_mem or not cupy_mem or not torch_mem):
        return w.text(), False
    _count, best = found
    # the headline is eagle.simulate's GPU wall, the arm its ratios and its
    # memory are quoted for -- not the cell's fastest arm, which on an
    # FP64-weak card can be the host (CPU) arm
    best = _by_arm(_cell(perf_gpu, n, WHY_CONFIG)).get("eagle_simulate", best)
    n_str, steps_str = f"{n:,}", str(WHY_CONFIG["max_steps"])
    caption = named_speedup_caption(speedup_pairs)

    w.add("::::{grid} 1 1 3 3")
    w.add(":class-container: strip")
    w.add(":gutter: 2")
    w.add("")
    w.add(f":::{{grid-item-card}} {pool.track(_fmt_sig_time(_center(best['wall_s'])))}")
    w.add(f"{pool.track(n_str)} samples (RK4), each stopping at its own step, up to "
          f"{pool.track(steps_str)} steps")
    w.add(":::")
    w.add(f":::{{grid-item-card}} {pool.track(big_text)}")
    w.add(f"than {pool.track(caption)} — {pool.track(n_str)} samples finishing at "
          f"different times, up to {pool.track(steps_str)} steps")
    w.add(":::")
    w.add(f":::{{grid-item-card}} {pool.track(mem_big_text)}")
    w.add(f"than CuPy and PyTorch — {pool.track(_n_words(n))} samples in "
          f"{pool.track(_fmt_mib_int(eagle_mem['device_peak_bytes']))}, "
          f"{pool.track(_fmt_ratio(eagle_mem['device_factor']))} the bare minimum state "
          f"(CuPy {pool.track(_fmt_ratio(cupy_mem['device_factor']))}, "
          f"PyTorch {pool.track(_fmt_ratio(torch_mem['device_factor']))})")
    w.add(":::")
    w.add("::::")
    return w.text(), True


def build_why_raptor(pool, perf_gpu, rk78_gpu):
    """``_generated/why_raptor.md``: the hero-adjacent comparison table +
    honest callouts. Returns (text, bars-for-the-chart, n, ok)."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    bars, n = why_raptor_bars(perf_gpu)
    if not bars:
        w.add("No committed GPU `perf_card` found yet.")
        return w.text(), [], None, False

    device = device_name(perf_gpu)
    w.add(f"| tool | wall (N = {pool.track(f'{n:,}')}, spread stop steps, up to "
          f"{pool.track(str(WHY_CONFIG['max_steps']))}) |")
    w.add("|---|---:|")
    for _arm, label, wall in bars:
        w.add(f"| {label} | {pool.track(_fmt_sig_time(wall))} |")
    w.add("")

    pct = simulate_vs_twin_kernel_pct(perf_gpu)
    _speedup_n, speedup_pairs = named_speedup(perf_gpu)
    big_text = named_speedup_big_text(speedup_pairs)
    if big_text and pct is not None:
        within = math.ceil(pct)
        caption = named_speedup_caption(speedup_pairs)
        w.add(f"`eagle_simulate` is {pool.track(big_text)} than {pool.track(caption)} "
              f"at this size, and its GPU time is within "
              f"{pool.track(str(within))}% of the hand-tuned version (`eagle_graph_auto`), "
              f"in every configuration this card runs.")
        w.add("")

    w.add("- **Tensor libraries compute every sample, every step** -- a masked array keeps "
          "computing the samples that already finished.")
    w.add("- **hawk + eagle skips finished samples** and packs the live ones into the next launch, "
          "so the batch keeps shrinking as samples finish.")
    tie = dense_tie_line(perf_gpu)
    if tie:
        verb = {"tie": "ties", "eagle": "trails", "warp": "beats"}[tie["verdict"]]
        wins = warp_wins_count(perf_gpu)
        lead = (f"it is the fastest arm in {pool.track(str(wins[0]))} of "
                f"{pool.track(str(wins[1]))} cells, and " if wins and wins[0] else "it ")
        w.add(f"- **Warp is excellent at per-thread kernels**: {lead}{pool.track(verb)} "
              f"hawk + eagle here on a fully "
              f"dense batch ({pool.track(_fmt_sig_time(tie['warp_s']))} vs "
              f"{pool.track(_fmt_sig_time(tie['eagle_s']))}) -- complementary tools, not a "
              f"hierarchy.")
    w.add("")
    w.add("RAPTOR adds, from the same source: per-sample Python, device-side stopping, "
          "forward- and reverse-mode derivatives, and the identical kernel on the CPU.")
    w.add("")

    honest78 = rk78_honest(rk78_gpu)
    if honest78:
        others = ", ".join(f"{label} {pool.track(_fmt_sig_time(s))}"
                            for label, s in honest78["others"])
        n78_str = f"{honest78['n']:,}"
        w.add(f"On the harder RK7(8) family (N = {pool.track(n78_str)} "
              f"adaptive Kepler orbits, every one inside its error bound): "
              f"{pool.track(honest78['fastest_label'])} "
              f"{pool.track(_fmt_sig_time(honest78['fastest_s']))}, {others}.")
        if honest78["cpu_label"] and honest78["cpu_beats_every_gpu_arm"]:
            w.add(f"hawk + eagle on the CPU alone, no GPU at all: "
                  f"{pool.track(_fmt_sig_time(honest78['cpu_s']))} -- the fastest number "
                  f"on this card, because this GPU's FP64 throughput is modest. Honest, "
                  f"and worth knowing before reaching for a GPU.")
        w.add("")

    link = "https://amasat01.github.io/eagle/content/performance.html"
    w.add(f"*Measured on {pool.track(device)}, a development GPU. "
          f"[Every number, every arm]({link}).*")
    return w.text(), bars, n, True


# --------------------------------------------------------------------------- #
# Landing hero fragments (index.md's "type A" redesign):
# the lead sentence under the H1, and the "How it compares" time + memory
# bar charts plus the honest note -- the mockup's plain HTML rows
# (track/fill/val, landing.css), not SVG. This retired the earlier
# hand-authored-style SVG comparison chart entirely (nothing references it
# once these fragments are wired into index.md -- the SVG files are kept
# only if still referenced). Every number here
# reuses the SAME computed values as hero_strip.md/honest_box.md/compare.md
# above (never re-derived), just reshaped for the hero's own markup.
# --------------------------------------------------------------------------- #
#: Chip-dot colour var per arm: eagle arms take
#: --mark-eagle (one value in both light and dark), every other tool its own
#: --tool-* chip -- the kit's one-colour-per-tool convention.
ARM_CHIP_VAR = {
    "eagle_simulate": "--mark-eagle", "eagle_graph": "--mark-eagle",
    "warp_kernel": "--tool-warp", "jax_vmap": "--tool-jax",
    "cupy_masked": "--tool-cupy", "torch_masked": "--tool-pytorch",
}
#: Headroom multiplier for the linear memory-ratio bar widths -- the
#: heaviest arm's bar never touches the track's right edge (mockup).
MEM_BAR_HEADROOM = 1.25


def _chart_label(card, arm):
    """The plain tool name the mockup's chart rows use (full "NVIDIA Warp",
    not the chart-cramped short form the old SVG needed): the card's own
    wording for eagle_graph (e.g. "eagle graph (device loop)" -- the same
    label `dense_tie_line`'s honest sentence already names it by), a fixed
    "eagle.simulate" for the hero arm, `COMPARISON_TOOL_NAMES` for the rest."""
    if arm == "eagle_simulate":
        return "eagle.simulate"
    if arm == "eagle_graph":
        return arm_label(card, arm)
    return COMPARISON_TOOL_NAMES.get(arm, arm_label(card, arm))


def _bar_row_html(label, chip_var, pct, value_text, is_us):
    """One `.row` of the mockup's plain HTML bar chart (landing.css): a chip
    dot in the tool's colour, the label, a track with a `.fill` at `pct`%
    and the value printed at the fill's own edge. `is_us` (an eagle arm)
    gets the `row us` class, which landing.css paints in --mark-raptor."""
    row_class = "row us" if is_us else "row"
    chip = f'<span class="chip" style="background:var({chip_var})"></span>' if chip_var else ""
    pct_s = f"{pct:.1f}"
    return (f'<div class="{row_class}"><div class="who">{chip}{label}</div>'
            f'<div class="track"><div class="fill" style="width:{pct_s}%"></div>'
            f'<span class="val" style="left:{pct_s}%">{value_text}</span></div></div>')


def build_lead_sentence(pool, perf_gpu):
    """``_generated/lead_sentence.md``: the hero's lead paragraph under the
    H1, matching hero_A's own wording exactly -- "... 179 ms and 74 MiB on a modest workstation GPU, 3.4x
    faster than NVIDIA Warp and 41x faster than PyTorch or CuPy." Two named
    ratios, both already computed by `named_speedup` (never re-derived):
    Warp's own floored ratio, and the CuPy/PyTorch one -- the smaller
    (never-overstate) of the two when they are not exactly equal, floored to
    2 significant figures same as everywhere else on this site."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    n = max(perf_gpu["ns"])
    found = fastest_of_cell(perf_gpu, n, WHY_CONFIG)
    eagle_mem = _mem_row(perf_gpu, "eagle_simulate", n, WHY_CONFIG)
    _speedup_n, speedup_pairs = named_speedup(perf_gpu)
    pairs_by_arm = dict(speedup_pairs)
    warp_ratio = pairs_by_arm.get("warp_kernel")
    other_ratios = [pairs_by_arm[a] for a in ("cupy_masked", "torch_masked") if a in pairs_by_arm]
    other_ratio = min(other_ratios) if other_ratios else None
    if not found or not eagle_mem or warp_ratio is None or other_ratio is None:
        return w.text(), False
    _count, best = found
    # the headline is eagle.simulate's GPU wall, the arm its ratios and its
    # memory are quoted for -- not the cell's fastest arm, which on an
    # FP64-weak card can be the host (CPU) arm
    best = _by_arm(_cell(perf_gpu, n, WHY_CONFIG)).get("eagle_simulate", best)
    sentence = (f"A million samples, each stopping at its own step: "
                f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))} and "
                f"{pool.track(_fmt_mib_int(eagle_mem['device_peak_bytes']))} on a modest workstation GPU, "
                f"{pool.track(_fmt_ratio(warp_ratio))} faster than NVIDIA Warp and "
                f"{pool.track(_fmt_ratio(other_ratio))} faster than PyTorch or CuPy. "
                f"The same Python source runs on your CPU.")
    # Raw HTML (like the other hero fragments below), not a bare MyST
    # paragraph: index.md needs the `rpt-lead` class on this one, and MyST's
    # `{include}` does not reliably nest a wrapping `{raw} html` fence around
    # it (see build_hero_strip's own docstring for the same constraint).
    w.add("```{raw} html")
    w.add(f'<p class="rpt-lead">{sentence}</p>')
    w.add("```")
    return w.text(), True


def build_compare_time_chart(pool, card, bars):
    """``_generated/compare_time_chart.md``: the "How it compares" wall-time
    bars, as the mockup's plain HTML rows (log-scale fill width)."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not bars:
        return w.text(), False
    lo = min(b[2] for b in bars) / 1.6
    hi = max(b[2] for b in bars) * 1.6
    aria = ", ".join(f"{_chart_label(card, arm)} {_fmt_sig_time(wall)}" for arm, _label, wall in bars)
    w.add("```{raw} html")
    w.add(f'<div class="chart" role="img" aria-label="Wall time: {aria}.">')
    for arm, _label, wall in bars:
        pct = 100 * (math.log10(wall) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        w.add(_bar_row_html(pool.track(_chart_label(card, arm)), ARM_CHIP_VAR.get(arm),
                             pct, pool.track(_fmt_sig_time(wall)), arm.startswith("eagle")))
    w.add("</div>")
    w.add(f'<p class="axis-note">Log scale, from {pool.track(_fmt_time(lo))} '
          f'to {pool.track(_fmt_time(hi))}.</p>')
    w.add("```")
    return w.text(), True


def build_compare_memory_chart(pool, card, rows):
    """``_generated/compare_memory_chart.md``: "Memory, as a multiple of what
    the samples need" -- the same `will_it_fit_rows` data compare.md's table
    already shows, as the mockup's linear HTML bars (lightest first, same
    row/track/fill markup as the time chart above)."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    factors = [f for _a, _b, f in rows if f is not None]
    if not rows or not factors:
        return w.text(), False
    aria = ", ".join(f"{_chart_label(card, arm)} {_fmt_ratio(factor)}"
                      for arm, _b, factor in rows if factor is not None)
    hi = max(factors) * MEM_BAR_HEADROOM
    w.add("```{raw} html")
    w.add(f'<div class="chart" role="img" '
          f'aria-label="Device memory as a multiple of the minimum: {aria}.">')
    for arm, _bytes, factor in rows:
        if factor is None:
            continue
        pct = 100 * factor / hi
        w.add(_bar_row_html(pool.track(_chart_label(card, arm)), ARM_CHIP_VAR.get(arm),
                             pct, pool.track(_fmt_ratio(factor)), arm.startswith("eagle")))
    w.add("</div>")
    w.add("```")
    return w.text(), True


def build_landing_honest(pool, perf_gpu):
    """``_generated/landing_honest.md``: the "How it compares" honest note --
    Warp's standing including the actual dense-tie wall times, eagle's own
    memory honesty (lower-level building blocks lighter than Warp), and the
    device/link fine print. Same primitives as honest_box.md
    (`warp_wins_count`, `dense_tie_line`, `will_it_fit_rows`), reworded into
    the mockup's 3-paragraph shape (never re-measured, only re-told). The
    Warp sentence names Warp's RK4 cell wins only when the card has any."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    wins = warp_wins_count(perf_gpu)
    tie = dense_tie_line(perf_gpu)
    if not wins or not tie:
        return w.text(), False
    rows, _n = will_it_fit_rows(perf_gpu)
    by_arm = {arm: factor for arm, _b, factor in rows}
    if not all(k in by_arm for k in ("eagle_graph", "warp_kernel", "eagle_simulate")):
        return w.text(), False
    steps_str = str(DENSE_CONFIG["max_steps"])
    verb = {"tie": "it ties hawk + eagle", "eagle": "hawk + eagle beats it",
            "warp": "it beats hawk + eagle"}[tie["verdict"]]
    device = device_name(perf_gpu)
    link = "https://amasat01.github.io/eagle/content/performance.html"

    w.add("```{raw} html")
    w.add('<div class="honest">')
    lead = (f"it is the fastest arm in {pool.track(str(wins[0]))} of the "
            f"{pool.track(str(wins[1]))} RK4 cells this card runs, and " if wins[0] else "")
    w.add(f"<p>NVIDIA Warp is an excellent per-thread kernel compiler: {lead}"
          f"when every sample runs all {pool.track(steps_str)} steps {pool.track(verb)} "
          f"({pool.track(_fmt_sig_time(tie['warp_s']))} against {pool.track(_fmt_sig_time(tie['eagle_s']))}).</p>")
    lighter = by_arm["eagle_graph"] < by_arm["warp_kernel"]
    w.add(f"<p>On memory, hawk + eagle's lower-level building blocks "
          f"{'go lighter than Warp' if lighter else 'and Warp compare'}: "
          f"{pool.track(_fmt_ratio(by_arm['eagle_graph']))} the minimum against Warp's "
          f"{pool.track(_fmt_ratio(by_arm['warp_kernel']))}. eagle.simulate keeps room to "
          f"compact the batch and uses {pool.track(_fmt_ratio(by_arm['eagle_simulate']))}.</p>")
    w.add(f'<p class="fine">Measured on {pool.track(device)}, a development GPU. '
          f'<a href="{link}">Every number, every arm</a>.</p>')
    w.add("</div>")
    w.add("```")
    return w.text(), True




# --------------------------------------------------------------------------- #
# The fuller "fastest arm, every batch size" summary (replaces the 80-row
# perf_glance.md table on the landing index): one compact grid per GPU/CPU
# card, configuration x N, naming only the arm that WON each cell.
# --------------------------------------------------------------------------- #
def fastest_arm_grid(pool, w, card, title):
    ns = card.get("ns") or []
    configs = card.get("configs") or []
    if not ns or not configs:
        return False
    w.add(f"**{pool.track(title)}.** Device: {pool.track(device_label(card))}.")
    w.add("")
    header = "| configuration | " + " | ".join(f"N = {pool.track(f'{n:,}')}" for n in ns) + " |"
    w.add(header)
    w.add("|---|" + "---|" * len(ns))
    for cfg in configs:
        dist, steps = cfg.get("distribution"), cfg.get("max_steps")
        label = f"{pool.track(dist)}, up to {pool.track(str(steps))} steps" if dist == "spread" else (
            f"{pool.track(dist)}, {pool.track(str(steps))} steps each" if dist else "single configuration")
        cells = []
        for n in ns:
            found = fastest_of_cell(card, n, cfg)
            if not found:
                cells.append("–")
                continue
            _count, best = found
            cells.append(f"{arm_label(card, best['arm'])} ({pool.track(_fmt_sig_time(_center(best['wall_s'])))})")
        w.add(f"| {label} | " + " | ".join(pool.track(c) for c in cells) + " |")
    w.add("")
    return True


def build_fastest_arm_grid(pool, perf_gpu, perf_cpu):
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    any_grid = False
    if perf_gpu:
        any_grid |= fastest_arm_grid(pool, w, perf_gpu, "Fastest arm, every batch size (GPU)")
    if perf_cpu:
        any_grid |= fastest_arm_grid(pool, w, perf_cpu, "Fastest arm, every batch size (CPU)")
    link = "https://amasat01.github.io/eagle/content/performance.html"
    w.add(f"Every arm, every column, every N: [eagle's performance page]({link}).")
    return w.text(), any_grid


# --------------------------------------------------------------------------- #
# compare.md's body: "How RAPTOR compares", organised by question.
# --------------------------------------------------------------------------- #
def build_compare_page(pool, perf_gpu, perf_cpu, rk78_gpu, rk78_cpu):
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    base = "https://amasat01.github.io/eagle/content/performance.html"
    any_section = False

    if perf_gpu:
        n = max(perf_gpu["ns"])
        spread_grid = [fastest_of_cell(perf_gpu, nn, WHY_CONFIG) for nn in perf_gpu["ns"]]
        if all(spread_grid):
            w.add("## My samples finish at different times")
            w.add("")
            w.add("A batch where each sample stops on its own step (the \"spread\" "
                  "distribution here) is exactly what eagle's compaction targets: once "
                  "enough samples finish, the live ones are packed into the next launch "
                  "instead of carrying the whole batch along.")
            w.add("")
            for nn, (count, best) in zip(perf_gpu["ns"], spread_grid):
                w.add(f"- N = {pool.track(f'{nn:,}')}: fastest is `{best['arm']}` "
                      f"({pool.track(arm_label(perf_gpu, best['arm']))}), "
                      f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))}, of "
                      f"{pool.track(str(count))} arms run.")
            w.add("")
            # Hyphenated to match the built page's docutils-normalized id
            # (the MyST target label itself is written with underscores;
            # see build_measured_on's own comment for why a literal external
            # link must pre-normalize instead of relying on MyST's rewrite).
            w.add(f"[Full table, this card]({base}#perf-card-gpu-"
                  f"{pool.track(perf_gpu.get('device_slug', ''))}).")
            w.add("")
            any_section = True

    tie = dense_tie_line(perf_gpu) if perf_gpu else None
    if tie:
        w.add("## My batch is dense (every sample runs the same number of steps)")
        w.add("")
        tie_n_str = f"{tie['n']:,}"
        noun = {"tie": "a tie", "eagle": "hawk + eagle's win", "warp": "Warp's win"}[tie["verdict"]]
        w.add(f"At N = {pool.track(tie_n_str)} with nothing to compact, "
              f"`warp_kernel` ({pool.track(_fmt_sig_time(tie['warp_s']))}) and "
              f"`{tie['eagle_arm']}` ({pool.track(_fmt_sig_time(tie['eagle_s']))}) are "
              f"{pool.track(noun)} -- a plain per-thread kernel is the better fit "
              "once nothing finishes early, and hawk + eagle's plain graph arm matches it.")
        w.add("")
        w.add(f"[Full table, this card]({base}#perf-card-gpu-"
              f"{pool.track(perf_gpu.get('device_slug', ''))}).")
        w.add("")
        any_section = True

    if perf_gpu:
        small_n = min(perf_gpu["ns"])
        small = [(cfg, fastest_of_cell(perf_gpu, small_n, cfg)) for cfg in perf_gpu["configs"]]
        small = [(cfg, found) for cfg, found in small if found]
        if small:
            w.add("## My batches are small")
            w.add("")
            w.add(f"At the smallest size this card runs (N = {pool.track(f'{small_n:,}')}), "
                  "launch and compaction overhead can cost more than they save:")
            w.add("")
            for cfg, (count, best) in small:
                cfg_label = f"{cfg.get('distribution')}, {cfg.get('max_steps')} steps"
                w.add(f"- {pool.track(cfg_label)}: fastest is `{best['arm']}` "
                      f"({pool.track(arm_label(perf_gpu, best['arm']))}), "
                      f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))}.")
            w.add("")
            any_section = True

    if perf_gpu:
        mem_rows, mem_n = will_it_fit_rows(perf_gpu)
        warp_mem_row = _mem_row(perf_gpu, "warp_kernel", mem_n, WHY_CONFIG) if mem_n else None
        graph_mem_row = _mem_row(perf_gpu, "eagle_graph", mem_n, WHY_CONFIG) if mem_n else None
        sim_mem_row = _mem_row(perf_gpu, "eagle_simulate", mem_n, WHY_CONFIG) if mem_n else None
        if mem_rows and warp_mem_row and graph_mem_row and sim_mem_row:
            w.add("## Will it fit on my GPU?")
            w.add("")
            w.add(f"Same cell as the speed comparison above (N = {pool.track(f'{mem_n:,}')}, spread stop "
                  f"steps, up to {pool.track(str(WHY_CONFIG['max_steps']))}): peak GPU memory the driver "
                  "accounted to the process, against the state the workload actually needs.")
            w.add("")
            w.add("| tool | GPU memory | × minimum |")
            w.add("|---|---:|---:|")
            for arm, peak_bytes, factor in mem_rows:
                label = MEMORY_TABLE_LABELS.get(arm, arm_label(perf_gpu, arm))
                w.add(f"| {pool.track(label)} | {pool.track(_fmt_mib_int(peak_bytes))} | "
                      f"{pool.track(_fmt_x(factor))} |")
            w.add("")
            w.add("Array libraries like CuPy, PyTorch and JAX keep a temporary for every operation in a "
                  "step, so their reservations stack up across the batch; hawk + eagle and NVIDIA Warp keep only "
                  "the per-sample state the workload itself needs. "
                  + memory_comparison_sentence(pool, sim_mem_row, warp_mem_row, graph_mem_row))
            w.add("")
            any_section = True

    honest78 = rk78_honest(rk78_gpu) if rk78_gpu else None
    if honest78:
        w.add("## My steps are adaptive")
        w.add("")
        w.add("The RK7(8) card integrates an adaptive-step orbit propagator (13-stage "
              "Runge-Kutta-Fehlberg, error-controlled) rather than a fixed-step scheme -- "
              "the same comparison, a heavier per-step workload:")
        w.add("")
        w.add(f"- fastest GPU arm: {pool.track(honest78['fastest_label'])}, "
              f"{pool.track(_fmt_sig_time(honest78['fastest_s']))}")
        for label, s in honest78["others"]:
            w.add(f"- {pool.track(label)}: {pool.track(_fmt_sig_time(s))}")
        if honest78["cpu_label"]:
            w.add(f"- {pool.track(honest78['cpu_label'])}: "
                  f"{pool.track(_fmt_sig_time(honest78['cpu_s']))}"
                  + (" -- beats every GPU arm above on this card" if honest78["cpu_beats_every_gpu_arm"] else ""))
        w.add("")
        w.add(f"[Full table, this card]({base}#rk78-card-gpu-"
              f"{pool.track(rk78_gpu.get('device_slug', ''))}).")
        w.add("")
        any_section = True

    w.add("## I need derivatives")
    w.add("")
    w.add("Every hawk kernel carries its reverse-mode (`hawk.diff.vjp`) and forward-mode "
          "(`hawk.diff.jvp`) derivative alongside the primal, generated from the same "
          "source and run on the GPU or CPU like the kernel itself. raptor's own demo "
          "(`examples/autodiff_vs_torch.py`, a hand-run script, not a committed card) "
          "measured hawk's vjp/jvp against `torch.autograd` on a Quadro P2000 -- see "
          "[raptor's README](https://github.com/amasat01/raptor#readme) for those numbers "
          "with their own method and caveats.")
    w.add("")
    any_section = True

    # RK7(8) CPU note: deliberately re-uses honest78's own number (the
    # eagle_cpu row embedded IN THE GPU CARD, same run as the GPU arms it is
    # compared against) rather than re-deriving a second figure from the
    # separately-run rk78_card_cpu card -- the two are different benchmark
    # runs of the same arm and can legitimately differ by double-digit
    # percent noise; showing both for "the same" claim one line apart would
    # read as a contradiction even though neither number is wrong.
    cpu_rows = []
    if perf_cpu:
        n = max(perf_cpu["ns"])
        found = fastest_of_cell(perf_cpu, n, WHY_CONFIG) or (
            fastest_of_cell(perf_cpu, n, perf_cpu["configs"][0]) if perf_cpu.get("configs") else None)
        if found:
            cpu_rows.append(("RK4 oscillators", n, found))
    if cpu_rows or honest78:
        w.add("## I want the CPU too")
        w.add("")
        w.add("Every kernel in this family runs unchanged on CPU threads (OpenMP), no GPU, "
              "no CUDA toolchain:")
        w.add("")
        for label, n, (_count, best) in cpu_rows:
            w.add(f"- {pool.track(label)}, N = {pool.track(f'{n:,}')}: "
                  f"{pool.track(arm_label(perf_cpu, best['arm']))}, "
                  f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))}.")
        if honest78 and honest78["cpu_label"] and honest78["cpu_beats_every_gpu_arm"]:
            w.add(f"- On the RK7(8) card, the CPU arm ({pool.track(honest78['cpu_label'])}, "
                  f"{pool.track(_fmt_sig_time(honest78['cpu_s']))}) beats every GPU arm "
                  "recorded there -- this GPU's FP64 throughput is modest; a data-centre "
                  "GPU is expected to flip this back.")
        w.add("")
        any_section = True

    w.add(f"Every number on this page traces to a committed card: "
          f"[eagle's performance page]({base}).")
    return w.text(), any_section


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("eagle_root", type=pathlib.Path)
    ap.add_argument("--out-dir", type=pathlib.Path, default=SITE_ROOT / "_generated")
    args = ap.parse_args(argv)

    pool = Pool(args.eagle_root)
    all_cards = {key: family_cards(pool, args.eagle_root, reldir, prefix)
                 for key, (reldir, prefix) in FAMILY_DIRS.items()}
    perf_gpu = reference_card(all_cards["perf_gpu"], REFERENCE_SLUGS["perf_gpu"])
    perf_cpu = reference_card(all_cards["perf_cpu"], REFERENCE_SLUGS["perf_cpu"])
    rk78_gpu = reference_card(all_cards["rk78_gpu"], REFERENCE_SLUGS["rk78_gpu"])
    rk78_cpu = reference_card(all_cards["rk78_cpu"], REFERENCE_SLUGS["rk78_cpu"])

    perf_glance, have_glance = build_perf_glance(pool, perf_gpu, perf_cpu, all_cards)

    if rk78_gpu:
        script_rel = rk78_gpu.get("script", "benchmarks/rk78_card/rk78_card.py")
        script_path = pool.source(script_rel)
        source_label = "the RK7(8) card"
        base_card = rk78_gpu
    elif perf_gpu:
        script_rel = perf_gpu.get("script", "benchmarks/perf_card/perf_card.py")
        script_path = pool.source(script_rel)
        source_label = "the RK4 card (the RK7(8) card has not been run yet)"
        base_card = perf_gpu
    else:
        base_card, script_path, source_label = None, None, None

    if base_card is not None and script_path.is_file():
        script_text = script_path.read_text()
        same_task_full, have_full = build_same_task(pool, base_card, script_text,
                                                      source_label, full=True)
        same_task_short, have_short = build_same_task(pool, base_card, script_text,
                                                        source_label, full=False)
    else:
        same_task_full = "<!-- Generated by tools/sync_cards.py; do not edit. -->\n\n" \
                          "No RK7(8) or RK4 card JSON found under the given eagle root yet.\n"
        same_task_short = same_task_full
        have_full = have_short = False

    hero_strip, have_hero = build_hero_strip(pool, perf_gpu)
    honest_box, have_honest = build_honest_box(pool, perf_gpu)
    why_raptor, why_bars, _why_n, have_why = build_why_raptor(pool, perf_gpu, rk78_gpu)
    fastest_grid, have_grid = build_fastest_arm_grid(pool, perf_gpu, perf_cpu)
    compare_page, have_compare = build_compare_page(pool, perf_gpu, perf_cpu, rk78_gpu, rk78_cpu)
    lead_sentence, have_lead = build_lead_sentence(pool, perf_gpu)
    compare_time_chart, have_time_chart = build_compare_time_chart(pool, perf_gpu, why_bars)
    mem_rows, _mem_n = will_it_fit_rows(perf_gpu) if perf_gpu else ([], None)
    compare_memory_chart, have_mem_chart = build_compare_memory_chart(pool, perf_gpu, mem_rows)
    landing_honest, have_landing_honest = build_landing_honest(pool, perf_gpu)
    cpu_glance, have_cpu_glance = build_cpu_glance(pool, all_cards["perf_cpu"])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "perf_glance.md").write_text(perf_glance)
    (args.out_dir / "same_task_full.md").write_text(same_task_full)
    (args.out_dir / "same_task_short.md").write_text(same_task_short)
    (args.out_dir / "hero_strip.md").write_text(hero_strip)
    (args.out_dir / "honest_box.md").write_text(honest_box)
    (args.out_dir / "why_raptor.md").write_text(why_raptor)
    (args.out_dir / "fastest_arm_grid.md").write_text(fastest_grid)
    (args.out_dir / "compare.md").write_text(compare_page)
    (args.out_dir / "lead_sentence.md").write_text(lead_sentence)
    (args.out_dir / "compare_time_chart.md").write_text(compare_time_chart)
    (args.out_dir / "compare_memory_chart.md").write_text(compare_memory_chart)
    (args.out_dir / "landing_honest.md").write_text(landing_honest)
    (args.out_dir / "cpu_glance.md").write_text(cpu_glance)

    (args.out_dir / "SOURCES.json").write_text(json.dumps(pool.as_json(), indent=2) + "\n")

    print(f"wrote {args.out_dir} (glance={have_glance}, "
          f"same_task full/short={have_full}/{have_short}, "
          f"hero_strip={have_hero}, honest_box={have_honest}, why_raptor={have_why}, "
          f"lead={have_lead}, time_chart={have_time_chart}, mem_chart={have_mem_chart}, "
          f"landing_honest={have_landing_honest}, cpu_glance={have_cpu_glance}, "
          f"grid={have_grid}, compare={have_compare}, "
          f"sources={len(pool.sources)}, numbers={len(pool.numbers)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
