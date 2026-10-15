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
- ``perf_switch.md``     -- index.md's "How it compares": On a GPU | On a CPU, device chips under it
- ``radar_detailed.md``  -- the detailed radar (both sides, own switch) for where_raptor_fits.md
- ``radar_gpu.md`` / ``radar_cpu.md`` -- the landing radar of each side (also embedded in
                             ``perf_switch.md`` under the device panels); its qualitative
                             axis is read from ``_data/radar_qualitative.json``
- ``compatibility.md``   -- what the cards measured, per device (driver, CUDA, compiler), included by
                             build_from_source.md
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
import html
import itertools
import json
import math
import pathlib
import re
import statistics
import sys
import textwrap
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import radar_icons  # noqa: E402
import visuals  # noqa: E402
import visuals_markup  # noqa: E402

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


#: CPU peak memory is published net of the benchmark harness's own copies
#: (a mirror of eagle's ``_card_common.harness_copy_bytes`` / ``net_peak_bytes``;
#: tests/test_sync_cards.py cross-checks the two against an eagle checkout).
#: The RK4 CPU card's eagle arms copy omega and zeta into separate float64
#: planes (16 bytes per sample) and their download returns copies of x, v and k
#: (20 bytes per sample); eagle needs neither. Every other arm is raw.
HARNESS_COPY_BYTES_PER_SAMPLE = 16 + 20
_HARNESS_COPY_ARMS = ("eagle_term", "eagle_compact", "eagle_reorder")


def harness_copy_bytes(arm, n):
    return HARNESS_COPY_BYTES_PER_SAMPLE * n if arm.startswith(_HARNESS_COPY_ARMS) else 0


def net_peak_bytes(row):
    """An RK4 CPU memory row's ``peak_bytes`` less the harness's copies; a
    negative result falls back to the measured value (below 1 MiB the
    allocator reuses memory already resident at the baseline)."""
    net = row["peak_bytes"] - harness_copy_bytes(row["arm"], row["n"])
    return net if net >= 0 else row["peak_bytes"]


CPU_MEMORY_NOTE = ("CPU peak memory is shown for N = 1,000,000 only, net of the benchmark harness's own copies "
                   "(36 bytes per sample on eagle's arms). At smaller N this harness cannot resolve it: each "
                   "measuring process inherits the launching process's peak, so smaller readings show that floor "
                   "rather than the workload. The cards keep the raw readings; the next card run measures every "
                   "size directly.")

#: A CPU memory probe inherits the launching process's resident size (its
#: ru_maxrss floor), so only N = 1e6 rows that clear their arm's small-N floor
#: by 8 MiB are published (mirror of eagle's ``floor_estimate`` /
#: ``is_resolved`` / ``published_peak_bytes``).
RESOLVED_N = 10**6
FLOOR_MARGIN_BYTES = 8 * 2**20


def floor_estimate(rows, arm=None):
    small = [r["peak_bytes"] + r["rss_baseline_bytes"] for r in rows
             if r["n"] <= 10**4 and (arm is None or r["arm"] == arm)]
    return max(small) if small else None


def published_peak_bytes(row, rows):
    """`net_peak_bytes` of a resolved row, None (no value) otherwise."""
    floor = floor_estimate(rows, row["arm"])
    if (floor is None or row["n"] != RESOLVED_N
            or row["peak_bytes"] + row["rss_baseline_bytes"] <= floor + FLOOR_MARGIN_BYTES):
        return None
    return net_peak_bytes(row)


def _fmt_x(value):
    """A ratio under the site's one rule (see `_round_sig_floor`)."""
    return "–" if value is None else _fmt_ratio(value)


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
        self.site_sources = {}   # path relative to the site root -> md5 (files this repo owns)
        self.numbers = set()
        self.uneven_eff = {}   # side -> device slug -> {"reference", "tools": {tool: {"arm", "efficiency_percent"}}}

    def source(self, relpath):
        p = self.eagle_root / relpath
        self.sources[str(relpath)] = _md5(p)
        return p

    def site_source(self, relpath):
        """A file of THIS repo (not eagle) that feeds the generated pages, recorded
        in SOURCES.json under ``site_sources`` so a change shows up in review."""
        p = SITE_ROOT / relpath
        self.site_sources[str(relpath)] = _md5(p)
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
            "site_sources": [{"path": k, "md5": v} for k, v in sorted(self.site_sources.items())],
            "uneven_efficiency": self.uneven_eff,
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
#: The driver accounts device memory in pages of about 2 MiB.
DRIVER_PAGE_BYTES = 2 * 2**20
#: Marks a device-memory figure borrowed from another card of the family.
BORROWED_MARK = "†"


def device_reading_valid(row):
    """False when a memory row's device reading is below the state the
    workload needs (less one driver page): the run cannot have fit in less,
    so the reading missed memory the library reserved before the baseline."""
    peak, minimum = row.get("device_peak_bytes"), row.get("minimum_bytes")
    if peak is None or not minimum:
        return True
    return peak + DRIVER_PAGE_BYTES >= minimum


DEVICE_NAMES = "benchmarks/device_names.json"


def display_cpu_model(pool, relpath, model):
    """The CPU name the pages print: the ``name`` eagle's ``benchmarks/device_names.json``
    gives the card's file stem, else the card's own model string."""
    table = pool.eagle_root / DEVICE_NAMES
    if not table.is_file():
        return model
    entry = json.loads(pool.source(DEVICE_NAMES).read_text()).get(pathlib.Path(relpath).stem)
    return entry["name"] if isinstance(entry, dict) and entry.get("name") else model


def load_card(pool, relpath):
    """The card's JSON, with every device reading `device_reading_valid`
    rejects withheld (``device_peak_bytes``/``device_factor`` None,
    ``device_withheld`` True) so no page quotes a number below the minimum."""
    path = pool.source(relpath)
    if not path.is_file():
        return None
    card = json.loads(path.read_text())
    card["_relpath"] = pathlib.PurePosixPath(*pathlib.Path(relpath).parts).as_posix()
    cpu = card.get("cpu")
    if isinstance(cpu, dict) and cpu.get("model"):
        cpu["model"] = display_cpu_model(pool, relpath, cpu["model"])
    elif isinstance(cpu, str) and cpu:
        card["cpu"] = display_cpu_model(pool, relpath, cpu)
    for row in (card.get("memory") or {}).get("rows", []):
        if not device_reading_valid(row):
            row["device_peak_bytes"] = None
            row["device_factor"] = None
            row["device_withheld"] = True
    return card


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
            card["_reference_stem"] = p.stem[len(prefix):]   # the key sol_reference.json uses
            out.append((card_slug(card, p, prefix), card))
    borrow_withheld_readings(out)
    return out


def borrow_withheld_readings(entries):
    """Fill each device reading `load_card` withheld with the family's other
    cards' reading for the same (arm, n), when those cards measured it validly
    with ONE value across every configuration -- an allocator's pool that does
    not depend on the card. The row records ``device_borrowed_from`` (device
    names); a (arm, n) the other cards disagree on stays withheld."""
    for slug, card in entries:
        for row in (card.get("memory") or {}).get("rows", []):
            if not row.get("device_withheld"):
                continue
            values, names = set(), set()
            for other_slug, other in entries:
                if other_slug == slug:
                    continue
                for r in (other.get("memory") or {}).get("rows", []):
                    if (r.get("arm") == row.get("arm") and r.get("n") == row.get("n")
                            and r.get("device_peak_bytes") is not None
                            and not r.get("device_withheld")):
                        values.add(r["device_peak_bytes"])
                        names.add(device_name(other))
            if len(values) == 1 and row.get("minimum_bytes"):
                peak = values.pop()
                row["device_peak_bytes"] = peak
                row["device_factor"] = peak / row["minimum_bytes"]
                row["device_borrowed_from"] = sorted(names)


def default_card(entries, preference):
    """The card whose device is first in `preference` (the tab shown by
    default, among cards that ran anything); every sentence that quotes a card's numbers quotes this one, so
    the text always matches the chart beside it."""
    ordered = in_tab_order([e for e in entries if e[1].get("ns")], preference)
    return ordered[0][1] if ordered else None


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
    w.add("| workload | arm | wall | × hawk + eagle | memory | compile (cold / warm) |")
    w.add("|---|---|---:|---:|---:|---:|")
    for cfg in configs or [{"distribution": None, "max_steps": None}]:
        dist, steps = cfg.get("distribution"), cfg.get("max_steps")
        cell = results_by_cell.get((dist, steps), [])
        if not cell:
            continue
        eagle_rows = [r for r in cell if r["arm"].startswith("eagle")]
        # the reference is eagle.simulate (the arm the hero and the headline quote), so
        # every page spells one ratio one way; a card without it uses its fastest eagle arm
        simulate = [_center(r["wall_s"]) for r in eagle_rows if r["arm"] == "eagle_simulate"]
        fastest_eagle = simulate[0] if simulate else min(
            (_center(r["wall_s"]) for r in eagle_rows), default=None)
        workload = f"spread S={steps}" if dist == "spread" else (
            f"uniform S={steps}" if dist == "uniform" else "(single configuration)")
        for r in sorted(cell, key=lambda r: _center(r["wall_s"])):
            arm = r["arm"]
            wall = _center(r["wall_s"])
            ratio = _fmt_x(wall / fastest_eagle) if fastest_eagle else "–"
            mrow = mem_by_key.get((n, dist, steps, arm))
            mem = _fmt_mib(((mrow or {}).get("device_peak_bytes")
                            if mrow is None or "device_peak_bytes" in mrow
                            else published_peak_bytes(mrow, card["memory"]["rows"])))
            if (mrow or {}).get("device_borrowed_from"):
                mem += BORROWED_MARK
            crow = compile_by_arm.get(arm)
            compile_cell = (f"{_fmt_time(crow['cold_s']['median'])} / "
                             f"{_fmt_time(crow['warm_s']['median'])}") if crow else "–"
            w.add(f"| {pool.track(workload)} | {arm_label(card, arm)} "
                  f"| {pool.track(_fmt_time(wall))} | {pool.track(ratio)} "
                  f"| {pool.track(mem)} | {pool.track(compile_cell)} |")
    w.add("")
    if any(r and "device_peak_bytes" not in r for r in mem_by_key.values()):
        w.add(CPU_MEMORY_NOTE)
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
# Tab order: ONE preference list per kind of device. The first card present in
# it is the tab a visitor sees; devices matching none follow alphabetically.
# --------------------------------------------------------------------------- #
#: Substrings of the lower-cased device name, best first.
#: The A100 card was measured with an automatic launch path that never took its
#: one-launch fast path; the L4 leads until the A100 is measured again.
GPU_PREFERENCE = ("h100", "l4", "a100", "t4", "p2000")
#: Newest server CPUs first (by name or by model-number family), then
#: workstation parts.
CPU_PREFERENCE = ("sapphire rapids", "platinum 84", "genoa", "epyc 9", "ice lake",
                  "platinum 83", "xeon w-", "threadripper", "ryzen")


def preference_rank(name, preference):
    """Index of the first `preference` substring in `name` (case-insensitive);
    after all of them when none matches."""
    low = re.sub(r"\((r|tm)\)", "", name.lower())
    for i, key in enumerate(preference):
        if key in low:
            return i
    return len(preference)


def in_tab_order(entries, preference):
    """``[(slug, card), ...]`` sorted by preference, then by device name."""
    return sorted(entries, key=lambda e: (preference_rank(device_name(e[1]), preference),
                                           device_name(e[1]).lower()))


# --------------------------------------------------------------------------- #
# One CPU card's chart (a panel of the "How it compares" switch).
# --------------------------------------------------------------------------- #
#: The tools charted on the landing page, in display order, with the plain
#: tool name each bar carries. The other arms (one thread, multiprocessing,
#: compaction, ...) live on eagle's full card, not here.
CPU_CHART_ARMS = (("eagle_term8", "eagle, 8 threads"), ("numba_prange", "Numba"),
                  ("jax_shard8", "JAX"), ("torch_masked", "PyTorch"),
                  ("numpy_masked", "NumPy"))
#: The configuration charted: the GPU chart's own (spread, S=1000).
CPU_CHART_CONFIG = {"distribution": "spread", "max_steps": 1000}
CPU_CHIP_VAR = {"eagle_term8": "--tool-raptor", "numba_prange": "--tool-numba",
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
    eff_html, _kept = eff_chart_html(pool, "cpu", card, n, CPU_CHIP_VAR)
    w.add("```{raw} html")
    if eff_html:
        w.add(BARS_TOGGLE)
        w.add('<div class="bars-view bars-wall">')
    w.add(f'<div class="chart" role="img" aria-label="Wall time on the CPU: {aria}.">')
    for arm, label, wall in bars:
        pct = 100 * (math.log10(wall) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        w.add(_bar_row_html(pool.track(label), CPU_CHIP_VAR.get(arm), pct,
                            pool.track(_fmt_sig_time(wall)), arm.startswith("eagle"),
                            info=run_info(pool, card, _cpu_row(card, arm, n), min(b[2] for b in bars))))
    w.add("</div>")
    cpu = card.get("cpu") or {}
    where = cpu_tab_label(card)
    if cpu.get("cores") and cpu.get("logical_cpus"):
        where += f" ({cpu['cores']} cores, {cpu['logical_cpus']} logical CPUs)"
    date = f", card of {card['generated_utc'][:10]}" if card.get("generated_utc") else ""
    anchor = f"{EAGLE_ANCHOR_FAMILY['perf_cpu']}-{slug}".replace("_", "-")
    w.add(f'<p class="axis-note">{pool.track(f"{n:,}")} samples, each stopping at its own step '
          f'(up to {CPU_CHART_CONFIG["max_steps"]:,}). {AXIS_RANGE_NOTE.format(lo=pool.track(_fmt_time(lo)), hi=pool.track(_fmt_time(hi)))} '
          f'Measured on {pool.track(where)}{pool.track(date)}. '
          f'<a href="{EAGLE_PERF_PAGE}#{anchor}">Every tool, every N, and where each one fits</a>.</p>')
    caption = card_caption_line(pool, card)
    if caption:
        w.add(caption)
    if eff_html:
        w.add("</div>")
        w.add('<div class="bars-view bars-eff">')
        w.add(eff_html)
        w.add("</div>")
    w.add("```")
    w.add("")
    return True


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
    "torch_graphed": "PyTorch with CUDA graphs", "torch_compiled": "PyTorch with torch.compile",
}


def fastest_arm_of_tool(card, arm, n, config=WHY_CONFIG):
    """The fastest arm of the tool that ``arm`` belongs to, in the (``n``, ``config``) cell of a GPU
    card: every number quoted for a tool uses that tool's fastest arm, never a fixed one (PyTorch has a
    masked, a CUDA-graph and a torch.compile arm; CuPy, JAX and Warp have one each). The raptor arms are
    left as named, they are the baseline the ratios are quoted for. ``arm`` itself when the cell has no
    arm of the tool."""
    return _fastest_arm_in(_by_arm(_cell(card, n, config)), arm)


def _fastest_arm_in(rows, arm):
    """`fastest_arm_of_tool` over ``rows`` ({arm: result row} of one cell)."""
    tool = radar_tool(arm, "gpu")
    if tool is None or arm.startswith("eagle"):
        return arm
    walls = {a: _center(r["wall_s"]) for a, r in rows.items() if radar_tool(a, "gpu") == tool}
    walls = {a: v for a, v in walls.items() if v and v > 0}
    return min(walls, key=walls.get) if walls else arm


def fastest_arm_with_memory(card, arm, n, config=WHY_CONFIG):
    """`fastest_arm_of_tool`, kept to the arms that have a device-memory reading: the tool's fastest
    arm when it has one, else its fastest arm that does."""
    tool = radar_tool(arm, "gpu")
    if tool is None or arm.startswith("eagle"):
        return arm
    fast = fastest_arm_of_tool(card, arm, n, config)
    if (_mem_row(card, fast, n, config) or {}).get("device_peak_bytes"):
        return fast
    walls = {a: _center(r["wall_s"]) for a, r in _by_arm(_cell(card, n, config)).items()
             if radar_tool(a, "gpu") == tool and (_mem_row(card, a, n, config) or {}).get("device_peak_bytes")}
    return min(walls, key=walls.get) if walls else arm


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
    """THE RATIO RULE: every ratio the site shows -- hero, lead sentence,
    tables, prose -- is `_round_sig_floor`ed to `sig` significant figures and
    spelled by this function, as "4.0×" / "41×", so one ratio has exactly one
    spelling wherever it appears (flooring an already-floored value is a
    no-op)."""
    if value is None or value <= 0:
        return "–"
    value = _round_sig_floor(value, sig)
    exp = math.floor(math.log10(value))
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
        arm = fastest_arm_with_memory(card, arm, n, config)
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
    "torch_graphed": "PyTorch with CUDA graphs", "torch_compiled": "PyTorch with torch.compile",
}


def will_it_fit_rows(card, arms=MEMORY_TABLE_ARMS, config=WHY_CONFIG):
    """[(arm, device_peak_bytes, device_factor), ...] for every `arms` entry
    the card ran at its largest N and `config`, lightest first."""
    if not card or not card.get("ns"):
        return [], None
    n = max(card["ns"])
    rows = []
    for arm in arms:
        arm = fastest_arm_with_memory(card, arm, n, config)
        row = _mem_row(card, arm, n, config)
        if row and row.get("device_peak_bytes") is not None:
            rows.append((arm, row["device_peak_bytes"], row.get("device_factor")))
    rows.sort(key=lambda r: r[1])
    return rows, n


def withheld_memory_arms(card, arms=MEMORY_TABLE_ARMS, config=WHY_CONFIG):
    """`arms` whose device reading at the card's largest N and `config` was
    withheld by `load_card`, in `arms` order."""
    if not card or not card.get("ns"):
        return []
    n = max(card["ns"])
    return [a for a in arms
            if (_mem_row(card, a, n, config) or {}).get("device_withheld")
            and not (_mem_row(card, a, n, config) or {}).get("device_borrowed_from")]


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
        arm = fastest_arm_of_tool(card, arm, n, config)
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
    bars = []
    for arm in arms:
        arm = fastest_arm_of_tool(card, arm, n, config)
        if arm in rows:
            label = COMPARISON_TOOL_NAMES[arm] if arm.startswith("torch_") else arm_label(card, arm)
            bars.append((arm, label, _center(rows[arm]["wall_s"])))
    bars.sort(key=lambda b: b[2])
    return bars, n


SOL_REFERENCE = "benchmarks/sol_reference.json"
#: FP64 pipe instructions per sample-step of the benchmark step (16 DFMA + 4 DMUL + 2 DADD), as in eagle's
#: tools/prose_claims.py `SOL_OPS_PER_STEP`; the sol_reference.json "ops_per_step" must agree.
SOL_OPS_PER_STEP = 22


def sol_reference(pool, card):
    """``(device key, entry)`` of the card's FP64 speed-of-light reference in eagle's
    benchmarks/sol_reference.json (read through the eagle root, its md5 recorded in SOURCES.json).
    A device with no entry at all is an error: nothing is guessed."""
    ref = json.loads(pool.source(SOL_REFERENCE).read_text())
    if ref.get("ops_per_step") != SOL_OPS_PER_STEP:
        raise ValueError(f"{SOL_REFERENCE}: ops_per_step {ref.get('ops_per_step')} != {SOL_OPS_PER_STEP}")
    stem = card.get("_reference_stem") or card.get("device_slug") or card.get("cpu_slug")
    stem = ref.get("aliases", {}).get(stem, stem)
    entry = ref["devices"].get(stem)
    if entry is None:
        raise ValueError(f"{SOL_REFERENCE}: no speed-of-light entry for device {stem!r}")
    return stem, entry


def sol_rate(entry):
    """R_SOL in sample-steps per second, or None while the device's reference is pending."""
    if entry.get("source") not in ("measured", "spec"):
        return None
    fma = entry.get("fma_per_s")
    if not isinstance(fma, (int, float)) or fma <= 0:
        raise ValueError(f"speed-of-light entry has no fma_per_s: {entry}")
    return fma / SOL_OPS_PER_STEP


def check_rows_under_sol(card, r_sol):
    """Fail when any row of the card runs above the speed of light: the reference is then wrong.
    Never clamps (same rule as eagle's tools/prose_claims.py ``eff``)."""
    for r in card.get("results") or []:
        rate = r.get("sample_steps_per_s")
        if rate and rate > r_sol:
            raise ValueError(f"row {r['arm']} n={r['n']} {r['distribution']} steps={r['max_steps']} runs at "
                             f"{rate / r_sol:.3f} x the speed of light; the reference must be re-measured")


def uneven_eff(card, arm, n, r_sol, spread=WHY_CONFIG):
    """``{"fraction", "spread", "sol"}``: the arm's ``sample_steps_per_s`` on the spread cell at N,
    over the device's R_SOL (a fraction of 1). None when the card has no such rate. A value above 1
    is an error, never clamped."""
    row = _by_arm(_cell(card, n, spread)).get(arm)
    rate = row.get("sample_steps_per_s") if row else None
    if not rate or not rate > 0:
        return None
    if rate > r_sol:
        raise ValueError(f"{arm} on {device_name(card)} reads {rate / r_sol:.3f} x the speed of light")
    return {"fraction": rate / r_sol, "spread": rate, "sol": r_sol}


def _fmt_eff(fraction):
    """An efficiency as a whole percent, floored (never rounded up); under 1 % as ``<1%``."""
    whole = math.floor(100.0 * fraction + 1e-9)
    return "<1%" if whole < 1 else f"{whole}%"


def _fmt_rate(rate):
    """A rate in sample-steps per second at three significant figures ("34.5 G")."""
    for scale, unit in ((1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
        if rate >= scale:
            return f"{rate / scale:.3g} {unit}"
    return f"{rate:.3g}"


#: (tool, arm prefix, the arm that names the tool's wall-time bar) per side. Like eagle's ``eff tool=...``
#: span, a tool's value is its FASTEST arm's rate (any arm with that prefix) at spread, S=1000, the largest N.
EFF_TOOLS = {
    "gpu": (("eagle", "eagle_", "eagle_simulate"), ("warp", "warp", "warp_kernel"), ("jax", "jax", "jax_vmap"),
            ("torch", "torch", "torch_masked"), ("cupy", "cupy", "cupy_masked")),
    "cpu": (("eagle", "eagle_", "eagle_term8"), ("numba", "numba", "numba_prange"), ("jax", "jax", "jax_shard8"),
            ("torch", "torch", "torch_masked"), ("numpy", "numpy", "numpy_masked")),
}


def eagle_bar_arm(kind):
    """The arm of eagle's headline wall-time bar on a ``kind`` card: the one arm eagle is quoted by."""
    return next(bar for tool, _p, bar in EFF_TOOLS[kind] if tool == "eagle")


def eff_arms(kind, card):
    """[(arm, label, bar arm)] one per tool the card ran: the tool's fastest arm at spread, S=1000, the
    largest N (``bar arm`` is the arm the wall-time bar of that tool shows); eagle's is its bar arm
    itself, so one eagle cell never shows two values on the landing page."""
    if not card.get("ns"):
        return []
    n = max(card["ns"])
    rows = _cell(card, n, WHY_CONFIG)
    out = []
    for _tool, prefix, bar_arm in EFF_TOOLS[kind]:
        fast = [r for r in rows if r["arm"].startswith(prefix) and r["arm"] != "eager_loop" and r.get("sample_steps_per_s")]
        if not fast:
            continue
        arm = max(fast, key=lambda r: r["sample_steps_per_s"])["arm"]
        if _tool == "eagle" and any(r["arm"] == bar_arm for r in fast):
            arm = bar_arm   # the landing page quotes eagle by the arm of its headline bar (eagle.simulate)
        label = _chart_label(card, bar_arm) if kind == "gpu" else dict(CPU_CHART_ARMS)[bar_arm]
        out.append((arm, label, bar_arm))
    return out


def eff_values(pool, kind, card):
    """``(device key, entry, [(arm, label, eff dict)] best first)`` for one card, or None when the card
    carries no sample_steps_per_s. The list is empty while the device's reference is pending."""
    if not card.get("ns") or not any(r.get("sample_steps_per_s") for r in card.get("results") or []):
        return None
    key, entry = sol_reference(pool, card)
    r_sol = sol_rate(entry)
    if r_sol is None:
        return key, entry, []
    check_rows_under_sol(card, r_sol)
    n = max(card["ns"])
    vals = []
    for arm, label, bar_arm in eff_arms(kind, card):
        v = uneven_eff(card, arm, n, r_sol)
        if v:
            vals.append((arm, label, dict(v, bar_arm=bar_arm)))
    vals.sort(key=lambda v: -v[2]["fraction"])
    return key, entry, vals


def eff_sources(pool, kind, entries):
    """{device slug: {"reference": {...}, "tools": {tool: {"arm", "efficiency_percent"}}}} recorded in SOURCES.json:
    the speed-of-light reference used and each charted tool's efficiency (unrounded percent)."""
    out = {}
    for slug, card in entries:
        got = eff_values(pool, kind, card)
        if got is None:
            continue
        key, entry, vals = got
        out[slug] = {"reference": {"key": key, "source": entry.get("source"), "fma_per_s": entry.get("fma_per_s")},
                     "tools": {radar_tool(arm, kind): {"arm": arm_label(card, arm),
                                                       "efficiency_percent": round(100.0 * v["fraction"], 2)}
                               for arm, _l, v in vals}}
    return out


def eff_info(pool, card, arm, n, v, entry):
    """The info lines of one efficiency bar, all from the card's row and the reference."""
    return [pool.track(x) for x in (
        arm_label(card, arm),
        _tab_device(card),
        f"N = {n:,}, up to {WHY_CONFIG['max_steps']:,} steps, samples stopping at different steps",
        f"measured: {_fmt_rate(v['spread'])} sample-steps per second",
        f"FP64 speed of light: {_fmt_rate(v['sol'])} sample-steps per second ({entry.get('source')} reference)",
        f"{_fmt_eff(v['fraction'])} of it",
        _card_stamp(card)) if x]


EFF_NOTE = ("Share of this device's FP64 speed of light a tool reaches when samples stop at different times. "
            "100% = every FP64 unit busy with useful work.")
EFF_PENDING = "Reference measurement pending for this device."
EAGLE_MECHANISM_EFF = "https://amasat01.github.io/eagle/content/performance/mechanism.html#efficiency-on-uneven-batches"


def eff_chart_html(pool, kind, card, n, chip_vars):
    """The "Uneven-batch efficiency" view of one device: ``(html, vals)``. Each bar is the tool's
    ``sample_steps_per_s`` on the spread cell (S=1000) at the card's largest N, the arm the wall-time
    bars use for that tool, over R_SOL = F_dev / 22 from eagle's sol_reference.json; best first. A device
    whose reference is pending gets one line instead of bars; ('', []) when the card has no rates."""
    got = eff_values(pool, kind, card)
    if got is None:
        return "", []
    _key, entry, vals = got
    link = f'<a href="{EAGLE_MECHANISM_EFF}">How the reference is measured</a>'
    if not vals:
        return f'<p class="axis-note eff-pending">{EFF_PENDING}</p>', []
    aria = ", ".join(f"{label} {_fmt_eff(v['fraction'])}" for _a, label, v in vals)
    out = [f'<div class="chart" role="img" aria-label="Uneven-batch efficiency on '
           f'{html.escape(_tab_device(card), quote=True)}: {aria}.">']
    for arm, label, v in vals:
        out.append(_bar_row_html(pool.track(label), chip_vars.get(v["bar_arm"]), 100.0 * v["fraction"],
                                 pool.track(_fmt_eff(v["fraction"])), arm.startswith("eagle"),
                                 info=eff_info(pool, card, arm, n, v, entry)))
    out.append("</div>")
    differs = [f"{label}: {arm_label(card, arm)}" for arm, label, v in vals if arm != v["bar_arm"]]
    which = f" Fastest arm per tool; {'; '.join(differs)}." if differs else ""
    out.append(f'<p class="axis-note">{EFF_NOTE}{pool.track(which)} {link}.</p>')
    return "\n".join(out), vals


BARS_TOGGLE = ('<div class="bars-toggle" role="group" aria-label="What the bars show">'
               '<button type="button" class="bars-opt" data-view="wall" aria-pressed="true">Wall time</button>'
               '<button type="button" class="bars-opt" data-view="eff" aria-pressed="false">'
               'Uneven-batch efficiency</button></div>')


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


def dense_tie_line(card, config=DENSE_CONFIG, eagle_arm=None):
    """The honest 'ties dense batches' callout: Warp vs the fastest `eagle*`
    arm at the dense config, largest N. {"verdict": "a tie"} when within 3%;
    otherwise whichever genuinely won, so this never overclaims if a future
    card re-run moves the numbers apart. ``eagle_arm`` pins the eagle side to one arm (the landing page
    quotes eagle.simulate) instead of the cell's fastest."""
    if not card or not card.get("ns"):
        return None
    n = max(card["ns"])
    rows = _by_arm(_cell(card, n, config))
    warp = rows.get("warp_kernel")
    eagle_candidates = [(a, r) for a, r in rows.items() if a.startswith("eagle")]
    pinned = [(a, r) for a, r in eagle_candidates if a == eagle_arm]
    eagle_candidates = pinned or eagle_candidates   # a card without the pinned arm falls back to its fastest
    if not warp or not eagle_candidates:
        return None
    best_arm, eagle_row = min(eagle_candidates, key=lambda ar: _center(ar[1]["wall_s"]))
    w, e = _center(warp["wall_s"]), _center(eagle_row["wall_s"])
    # "tie" (noun) / "warp" / "eagle" (which one actually won) -- each call
    # site below phrases this in its own grammar; never a shared adjective.
    verdict = "tie" if 0.97 <= e / w <= 1.03 else ("eagle" if e < w else "warp")
    return {"n": n, "warp_s": w, "eagle_arm": best_arm,
            "eagle_label": arm_label(card, best_arm), "eagle_s": e, "verdict": verdict,
            "eagle_name": "eagle.simulate" if best_arm == "eagle_simulate" else "hawk + eagle"}


def dense_clause(pool, tie):
    """The dense-batch comparison as one clause, the subject and its own number
    first, the other side's number attributed: "hawk + eagle beats it: 211 ms
    against Warp's 220 ms" ("it" is Warp)."""
    warp = pool.track(_fmt_sig_time(tie["warp_s"]))
    eagle = pool.track(_fmt_sig_time(tie["eagle_s"]))
    name = tie.get("eagle_name", "hawk + eagle")
    if tie["verdict"] == "eagle":
        return f"{name} beats it: {eagle} against Warp's {warp}"
    verb = "ties" if tie["verdict"] == "tie" else "beats"
    return f"it {verb} {name}: {warp} against {name}'s {eagle}"


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
    others = []
    for a in RK78_HONEST_ARMS:
        a = _fastest_arm_in(rows, a)
        if a in rows:
            others.append((arm_label(card, a), _center(rows[a]["wall_s"])))
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
    line = (f"Measured on {pool.track(device)}. NVIDIA Warp's "
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


#: Within this relative gap two walls are "level" in prose.
TIE_BAND = 0.03
#: The tools `build_compaction_numbers` ranks `eagle.simulate` against.
COMPACTION_VS_ARMS = ("warp_kernel", "jax_vmap", "cupy_masked", "torch_masked")


def build_compaction_numbers(pool, perf_gpu):
    """``_generated/compaction_numbers.md``: the worked compaction numbers of
    where_raptor_fits.md, for the same headline device and cell as the rest of
    the site (the default GPU card, its largest N, `WHY_CONFIG` / `DENSE_CONFIG`).
    Every figure is read from the card; every comparative word ("ahead of",
    "the better fit", "faster than every GPU arm") is decided by the numbers,
    so a card re-run on a different GPU can change the sentence, never leave a
    claim the card no longer supports."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    n = max(perf_gpu["ns"])
    spread = _by_arm(_cell(perf_gpu, n, WHY_CONFIG))
    dense = _by_arm(_cell(perf_gpu, n, DENSE_CONFIG))
    need = ("eagle_graph", "eagle_graph_compact", "eagle_graph_reorder", "eagle_simulate")
    if any(a not in spread or a not in dense for a in need):
        return w.text(), False

    def wall(rows, arm):
        return _center(rows[arm]["wall_s"])

    def t(seconds):
        return pool.track(_fmt_time(seconds))

    def vs(a, b):
        return "ahead" if a < b * (1 - TIE_BAND) else ("behind" if a > b * (1 + TIE_BAND) else "level")

    steps = str(WHY_CONFIG["max_steps"])
    w.add(f"The [performance card]({EAGLE_PERF_PAGE}) measures this on {pool.track(device_name(perf_gpu))}, "
          f"{pool.track(_n_words(n))} samples integrated for up to {pool.track(steps)} steps.")
    w.add("")
    w.add("On a batch where samples finish at different times:")
    w.add("")
    g, c, r, sim = (wall(spread, a) for a in need)
    if c < g:
        w.add(f"- the compacted graph takes {t(c)}, against {t(g)} for the identical workload run without "
              "compaction — what compaction itself saves at fixed work;")
    else:
        w.add(f"- the compacted graph takes {t(c)}, against {t(g)} for the identical workload run without "
              "compaction — at this size compaction costs more than it saves;")
    if r < c:
        w.add(f"- an occasional physical reorder layered on top, opt-in and triggered only once the live "
              f"samples have thinned and scattered, cuts that further to {t(r)};")
    else:
        w.add(f"- an occasional physical reorder layered on top, opt-in and triggered only once the live "
              f"samples have thinned and scattered, takes {t(r)}, no faster than compaction alone;")
    others = [(a, wall(spread, a)) for a in (fastest_arm_of_tool(perf_gpu, b, n, WHY_CONFIG) for b in COMPACTION_VS_ARMS)
              if a in spread]
    ahead = [(a, x) for a, x in others if vs(sim, x) == "ahead"]
    rest = [(a, x) for a, x in others if vs(sim, x) != "ahead"]

    def named(items):
        return [f"{pool.track(COMPARISON_TOOL_NAMES.get(a, a))} ({t(x)})" for a, x in items]

    def joined(parts):
        return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]

    line = ("- `eagle.simulate` — the policy that picks between these approaches at run time, so nobody has "
            f"to choose by hand — reaches {t(sim)} on this same batch")
    if ahead:
        line += f", ahead of {joined(named(ahead))}"
    if rest:
        line += ("; " if ahead else ", while ") + joined(named(rest)) + (
            " is" if len(rest) == 1 else " are") + " level with it or faster"
    w.add(line + " on this card.")
    w.add("")

    gu, cu, su = (wall(dense, a) for a in ("eagle_graph", "eagle_graph_compact", "eagle_simulate"))
    text = (f"On a batch where every sample runs the full {pool.track(steps)} steps instead, there is nothing "
            "to compact, and ")
    if gu < cu:
        text += (f"the plain graph is the better fit: {t(gu)} against {t(cu)} for the compacted graph, "
                 "whose periodic active-set scan runs with no idle lanes left to recover.")
    else:
        text += f"the compacted graph still comes out ahead: {t(cu)} against {t(gu)} for the plain graph."
    warp = dense.get("warp_kernel")
    if warp is not None:
        wu = _center(warp["wall_s"])
        verdict = vs(su, wu)
        if verdict == "level":
            text += (f" NVIDIA Warp's per-thread kernel and `eagle.simulate` tie here ({t(wu)} and {t(su)})")
        elif verdict == "ahead":
            text += f" `eagle.simulate` is the faster of the two here ({t(su)} against NVIDIA Warp's {t(wu)})"
        else:
            text += f" NVIDIA Warp's per-thread kernel is the faster of the two here ({t(wu)} against {t(su)})"
        small = _by_arm(_cell(perf_gpu, 10_000, DENSE_CONFIG)) if 10_000 in perf_gpu["ns"] else {}
        if "warp_kernel" in small and "eagle_simulate" in small:
            ws, ss = wall(small, "warp_kernel"), wall(small, "eagle_simulate")
            word = {"level": "the two are level", "ahead": "`eagle.simulate` leads",
                    "behind": "NVIDIA Warp leads"}[vs(ss, ws)]
            text += f", and at N = {pool.track('10,000')} {word} ({t(ss)} against {t(ws)})"
        text += " — worth knowing about."
    text += " The card also lists the regimes where another approach is the better fit:"
    cpu = dense.get("cpu_openmp")
    gpu_best = min(wall(dense, a) for a in dense if a != "cpu_openmp")
    clauses = []
    if cpu is not None and _center(cpu["wall_s"]) < gpu_best:
        clauses.append(f" on this card the 8-thread CPU build is faster than every GPU arm on the dense "
                       f"batch ({t(_center(cpu['wall_s']))} against {t(su)})")
    if "cupy_masked" in dense:
        clauses.append(" the same computation written as masked CuPy array code is the better fit when "
                       "array-style code matters more than wall time")
    if not clauses:
        return w.text(), False
    text += ",".join(clauses[:1]) + (", and" + clauses[1] if len(clauses) > 1 else "") + "."
    w.add(text)
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
    cupy_arm = fastest_arm_with_memory(perf_gpu, "cupy_masked", n, WHY_CONFIG)
    torch_arm = fastest_arm_with_memory(perf_gpu, "torch_masked", n, WHY_CONFIG)
    cupy_mem = _mem_row(perf_gpu, cupy_arm, n, WHY_CONFIG)
    torch_mem = _mem_row(perf_gpu, torch_arm, n, WHY_CONFIG)
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
    cupy_name, torch_name = COMPARISON_TOOL_NAMES[cupy_arm], COMPARISON_TOOL_NAMES[torch_arm]
    w.add(f"than {pool.track(cupy_name)} and {pool.track(torch_name)} — {pool.track(_n_words(n))} samples in "
          f"{pool.track(_fmt_mib_int(eagle_mem['device_peak_bytes']))}, "
          f"{pool.track(_fmt_ratio(eagle_mem['device_factor']))} the bare minimum state "
          f"({cupy_name} {pool.track(_fmt_ratio(cupy_mem['device_factor']))}, "
          f"{torch_name} {pool.track(_fmt_ratio(torch_mem['device_factor']))})")
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
        wins = warp_wins_count(perf_gpu)
        lead = (f"it is the fastest arm in {pool.track(str(wins[0]))} of "
                f"{pool.track(str(wins[1]))} cells, and " if wins and wins[0] else "")
        w.add(f"- **Warp is excellent at per-thread kernels**: {lead}on a fully dense batch "
              f"{dense_clause(pool, tie)} -- complementary tools, not a hierarchy.")
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
    w.add(f"*Measured on {pool.track(device)}. "
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
    "eagle_simulate": "--tool-raptor", "eagle_graph": "--tool-raptor",
    "warp_kernel": "--tool-warp", "jax_vmap": "--tool-jax",
    "cupy_masked": "--tool-cupy", "torch_masked": "--tool-pytorch",
    "torch_graphed": "--tool-pytorch", "torch_compiled": "--tool-pytorch",
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


def _bar_row_html(label, chip_var, pct, value_text, is_us, info=None):
    """One `.row` of the mockup's plain HTML bar chart (landing.css): a chip
    dot in the tool's colour, the label, a track with a `.fill` at `pct`%
    and the value printed at the fill's own edge. `is_us` (an eagle arm)
    gets the `row us` class, which landing.css paints in --mark-raptor.

    `info` (a list of strings, all taken from the card) makes the row
    focusable and adds the `.rinfo` line that hover, focus, a tap or Enter
    reveals (see `_static/js/perf-state.js`); the row's fill takes the tool's
    own colour (``--tool``) while the row is hovered or focused."""
    row_class = "row us" if is_us else "row"
    chip = f'<span class="chip" style="background:var({chip_var})"></span>' if chip_var else ""
    pct_s = f"{pct:.1f}"
    extra, tail = "", ""
    if info:
        text = html.escape(" · ".join(info), quote=True)
        tool = f"--tool:var({chip_var})" if chip_var else "--tool:var(--mark-neutral)"
        extra = (f' tabindex="0" role="group" aria-expanded="false" '
                 f'aria-label="{html.escape(str(label), quote=True)}: {html.escape(str(value_text), quote=True)}. {text}" '
                 f'style="{tool}"')
        tail = ('<div class="rinfo">'
                + "<br>".join(_stamp_html(i) if isinstance(i, LinkedStamp) else html.escape(i) for i in info)
                + "</div>")
    return (f'<div class="{row_class}"{extra}><div class="who">{chip}{label}</div>'
            f'<div class="track"><div class="fill" style="width:{pct_s}%"></div>'
            f'<span class="val" style="left:{pct_s}%">{value_text}</span></div>{tail}</div>')


def _cfg_phrase(dist, steps):
    """How a cell's stop rule reads in one run's info line."""
    if dist == "spread":
        return f"spread, up to {steps:,} steps"
    if dist == "uniform":
        return f"uniform, {steps:,} steps each"
    return "single configuration"


def _tab_device(card):
    """The device as its chip names it (CPU: without trademarks and clock)."""
    return cpu_tab_label(card) if isinstance(card.get("cpu"), dict) else device_name(card)


#: The repository and tag the cards' committed files are linked at.
EAGLE_REPO_URL = "https://github.com/amasat01/eagle"
EAGLE_CARD_TAG = "v0.6.0"


def card_url(card):
    """Where the card's committed JSON lives in the eagle repository at the release tag, or None."""
    rel = card.get("_relpath")
    return f"{EAGLE_REPO_URL}/blob/{EAGLE_CARD_TAG}/{rel}" if rel else None


class LinkedStamp(str):
    """A card stamp ("card of <date>, script <hash>") that knows the card file it names; the bar's
    info panel renders the script hash as a link to it, the aria-label keeps the plain text."""
    href = None


def _card_stamp(card):
    """'card of <date>, script <short md5>' -- the card's own identity; the script part links to the
    card's file when the stamp is shown in a bar's info panel."""
    date = (card.get("generated_utc") or "")[:10]
    md5 = (card.get("script_md5") or "")[:8]
    bits = [f"card of {date}" if date else "", f"script {md5}" if md5 else ""]
    stamp = LinkedStamp(", ".join(b for b in bits if b))
    stamp.href = card_url(card) if md5 else None
    return stamp


def _stamp_html(stamp):
    """The stamp as escaped HTML, its "script <hash>" part a link to the card file."""
    text = html.escape(str(stamp))
    href = getattr(stamp, "href", None)
    m = re.search(r"script [0-9a-f]+", str(stamp))
    if not href or not m:
        return text
    return text.replace(m.group(0), f'<a href="{html.escape(href, quote=True)}" target="_blank" '
                                    f'rel="noopener">{m.group(0)}</a>')


def _kernel_ver(cuda_int):
    """12090 -> "12.9" (the CUDA version integer as the card records it)."""
    return f"{cuda_int // 1000}.{(cuda_int % 1000) // 10}" if isinstance(cuda_int, int) and cuda_int else None


def card_environment_line(card):
    """One line of what the card itself records about the machine and the tools it ran: host CPU,
    GPU driver, CUDA runtime and driver API, and the versions of Warp, JAX, PyTorch and CuPy (a GPU
    card), or the CPU, platform and Python (a CPU card). Only what the card has; '' when it has none."""
    parts = []
    soft = card.get("software") or {}
    dev = card.get("device") or {}
    if isinstance(card.get("cpu"), dict):
        c = card["cpu"]
        where = c.get("model") or ""
        if c.get("cores") and c.get("logical_cpus"):
            where += f" ({c['cores']} cores, {c['logical_cpus']} logical CPUs)"
        parts.append(f"Host CPU {where}" if where else "")
        parts.append(f"{card['platform']}" if card.get("platform") else "")
        py = (card.get("toolchain") or {}).get("python")
        parts.append(f"Python {py}" if py else "")
    else:
        parts.append(f"Host CPU {soft['cpu']}" if soft.get("cpu") else "")
        parts.append(f"GPU driver {dev['driver_version']}" if dev.get("driver_version") else "")
        rt, api = _kernel_ver(dev.get("cuda_runtime")), _kernel_ver(dev.get("cuda_driver_api"))
        if rt or api:
            parts.append("CUDA " + ", ".join(b for b in (f"runtime {rt}" if rt else "", f"driver API {api}" if api else "") if b))
        tools = [f"{name} {soft[key]}" for name, key in (("Warp", "warp"), ("JAX", "jax"),
                                                         ("PyTorch", "torch"), ("CuPy", "cupy")) if soft.get(key)]
        parts.append(", ".join(tools))
    return "; ".join(b for b in parts if b)


def card_caption_line(pool, card):
    """The caption line every card's bars carry: the environment the card recorded and the link to
    the card file at the release tag ('' when the card has neither)."""
    env = card_environment_line(card)
    url = card_url(card)
    link = (f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
            f'{html.escape(pathlib.PurePosixPath(card["_relpath"]).name)}</a>' if url else "")
    if not env and not link:
        return ""
    text = html.escape(env) + ("." if env else "")
    return f'<p class="axis-note card-env">{pool.track(text)}{" Card file: " + link + "." if link else ""}</p>'


def _clock_note(row):
    """The clock the run was timed at, from the row's own readings (GPU: the
    SM clock per repetition; CPU: the core clock when the timer started)."""
    if row.get("sm_mhz"):
        return f"SM clock {statistics.median(row['sm_mhz']):.0f} MHz"
    if row.get("cpu_mhz_at_timer_start"):
        return f"core clock {row['cpu_mhz_at_timer_start']:.0f} MHz at the start"
    return ""


def run_info(pool, card, row, fastest):
    """The info lines of one wall-time bar, every figure read off the card's
    row: arm, device and clock, cell, statistic with median and IQR, repeats,
    ratio to the fastest bar, card date and script version, and the card's
    own note for the arm when it has one."""
    stat = row["wall_s"]
    method = card.get("method") or {}
    lines = [arm_label(card, row["arm"]),
             ", ".join(b for b in (_tab_device(card), _clock_note(row)) if b),
             f"N = {row['n']:,}, {_cfg_phrase(row.get('distribution'), row.get('max_steps'))}"]
    median = stat.get("median")
    iqr = stat.get("iqr")
    if median is not None and iqr is not None:
        label = method.get("statistic") if isinstance(method.get("statistic"), str) else "centre"
        lines.append(f"bar = {label}; median {_fmt_sig_time(median)}, IQR {_fmt_sig_time(iqr)}")
    reps = len(stat.get("samples") or []) or row.get("repetitions")
    if reps:
        lines.append(f"{reps} repeats")
    if fastest:
        lines.append(f"{_fmt_ratio(_center(stat) / fastest)} the fastest bar")
    lines.append(_card_stamp(card))
    not_run = (card.get("arms_not_run") or {}).get(row["arm"])
    if not_run:
        lines.append(f"not run: {not_run}")
    return [pool.track(x) for x in lines if x]


def build_lead_sentence(pool, perf_gpu):
    """``_generated/lead_sentence.md``: the hero's lead paragraph under the H1: eagle.simulate's wall
    and memory on the default GPU, then each compared tool's OWN floored ratio ("2.5x faster than NVIDIA
    Warp, 76x faster than JAX, ..."), every one from `named_speedup` -- the same cell and the same
    fastest arm of the tool the bars show, never one number shared by two tools."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not perf_gpu or not perf_gpu.get("ns"):
        return w.text(), False
    n = max(perf_gpu["ns"])
    found = fastest_of_cell(perf_gpu, n, WHY_CONFIG)
    eagle_mem = _mem_row(perf_gpu, "eagle_simulate", n, WHY_CONFIG)
    _speedup_n, speedup_pairs = named_speedup(perf_gpu)
    # each tool its own ratio, floored (never overstated), from the same cell and arm the bars use;
    # smallest first so the sentence reads as a climb
    ratios = sorted(((r, COMPARISON_TOOL_NAMES[a]) for a, r in speedup_pairs if r is not None))
    if not found or not eagle_mem or not ratios:
        return w.text(), False
    _count, best = found
    # the headline is eagle.simulate's GPU wall, the arm its ratios and its
    # memory are quoted for -- not the cell's fastest arm, which on an
    # FP64-weak card can be the host (CPU) arm, or eagle's lower-level graph call
    best = _by_arm(_cell(perf_gpu, n, WHY_CONFIG)).get("eagle_simulate", best)
    named = [f"{pool.track(_fmt_ratio(r))} faster than {name}" for r, name in ratios]
    joined = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
    sentence = (f"{_n_words(n).capitalize()} samples, each stopping at its own step: "
                f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))} and "
                f"{pool.track(_fmt_mib_int(eagle_mem['device_peak_bytes']))} on {pool.track(device_name(perf_gpu))}, "
                f"{joined}. "
                f"The same Python source runs on your CPU.")
    # Raw HTML (like the other hero fragments below), not a bare MyST
    # paragraph: index.md needs the `rpt-lead` class on this one, and MyST's
    # `{include}` does not reliably nest a wrapping `{raw} html` fence around
    # it (see build_hero_strip's own docstring for the same constraint).
    w.add("```{raw} html")
    w.add(f'<p class="rpt-lead">{sentence}</p>')
    dense = dense_hero_line(pool, perf_gpu)
    if dense:
        w.add(f'<p class="rpt-lead-dense">{dense}</p>')
    w.add("```")
    return w.text(), True


def dense_hero_line(pool, card):
    """The dense-batch case in one line under the hero, from the same cell the honest note uses
    (`dense_tie_line`, eagle.simulate against Warp, every sample running all steps): a tie when the two are
    within 3%, otherwise whichever won. '' when the card lacks either arm."""
    tie = dense_tie_line(card, eagle_arm="eagle_simulate")
    if not tie:
        return ""
    steps = pool.track(f"{DENSE_CONFIG['max_steps']:,}")
    warp, eagle = pool.track(_fmt_sig_time(tie["warp_s"])), pool.track(_fmt_sig_time(tie["eagle_s"]))
    head = f"When every sample runs the same {steps} steps, "
    if tie["verdict"] == "tie":
        return f"{head}eagle.simulate and NVIDIA Warp tie: {eagle} against {warp}."
    winner = "eagle.simulate" if tie["verdict"] == "eagle" else "NVIDIA Warp"
    return f"{head}{winner} is the faster: {eagle} for eagle.simulate, {warp} for NVIDIA Warp."


#: The wall-time axis is drawn from the bars of that view only: a margin (a factor of 1.6) below the
#: fastest and above the slowest bar, so no bar sits on an edge. Said on the page, so a reader does not
#: look for an arm that sits at the left end.
AXIS_RANGE_NOTE = ("Log scale; the axis runs from {lo} to {hi}, a margin around the fastest and the "
                   "slowest bar shown.")


def gpu_chart_block(pool, w, slug, card):
    """One GPU's wall-time bars (log scale) at the card's largest N, for the
    `WHY_CONFIG` workload. False (nothing written) without eagle's row."""
    bars, n = why_raptor_bars(card)
    if not bars:
        return False
    lo = min(b[2] for b in bars) / 1.6
    hi = max(b[2] for b in bars) * 1.6
    aria = ", ".join(f"{_chart_label(card, arm)} {_fmt_sig_time(wall)}" for arm, _label, wall in bars)
    eff_html, _kept = eff_chart_html(pool, "gpu", card, n, ARM_CHIP_VAR)
    w.add("```{raw} html")
    if eff_html:
        w.add(BARS_TOGGLE)
        w.add('<div class="bars-view bars-wall">')
    w.add(f'<div class="chart" role="img" aria-label="Wall time on {device_name(card)}: {aria}.">')
    rows_by_arm = _by_arm(_cell(card, n, WHY_CONFIG))
    for arm, _label, wall in bars:
        pct = 100 * (math.log10(wall) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        w.add(_bar_row_html(pool.track(_chart_label(card, arm)), ARM_CHIP_VAR.get(arm),
                             pct, pool.track(_fmt_sig_time(wall)), arm.startswith("eagle"),
                             info=run_info(pool, card, rows_by_arm[arm], bars[0][2])))
    w.add("</div>")
    date = f", card of {card['generated_utc'][:10]}" if card.get("generated_utc") else ""
    anchor = f"{EAGLE_ANCHOR_FAMILY['perf_gpu']}-{slug}".replace("_", "-")
    w.add(f'<p class="axis-note">{pool.track(f"{n:,}")} samples, each stopping at its own step '
          f'(up to {WHY_CONFIG["max_steps"]:,}). {AXIS_RANGE_NOTE.format(lo=pool.track(_fmt_time(lo)), hi=pool.track(_fmt_time(hi)))} '
          f'Measured on {pool.track(device_label(card))}'
          f'{pool.track(date)}. <a href="{EAGLE_PERF_PAGE}#{anchor}">Every tool, every N, '
          f'and where each one fits</a>.</p>')
    caption = card_caption_line(pool, card)
    if caption:
        w.add(caption)
    if eff_html:
        w.add("</div>")
        w.add('<div class="bars-view bars-eff">')
        w.add(eff_html)
        w.add("</div>")
    w.add("```")
    w.add("")
    return True


# --------------------------------------------------------------------------- #
# "How it compares" -- one block with two levels of switching: the hardware
# (On a GPU | On a CPU) and, under it, the device chips of that side. Plain
# radio inputs and CSS (_static/custom.css, `.perf-switch`): keyboard and
# screen-reader semantics come with the radios, and without script the first
# device of the GPU side shows.
# --------------------------------------------------------------------------- #
_RAW_RE = re.compile(r"```\{raw\} html\n(.*?)\n```", re.S)
GPU_ONLY_NOTE = ("Memory and the NVIDIA Warp comparison are GPU measurements: "
                 "pick <em>On a GPU</em> to see them.")


def _raw_html(text):
    """The HTML inside a generated ```{raw} html fence ('' if there is none)."""
    m = _RAW_RE.search(text)
    return m.group(1) if m else ""


def _gpu_panel(pool, slug, card):
    """The HTML of one GPU's panel: wall-time bars, memory bars, the honest
    note -- each only when the card has the data."""
    bw = Writer(pool)
    if not gpu_chart_block(pool, bw, slug, card):
        return ""
    parts = [_raw_html(bw.text())]
    rows, _n = will_it_fit_rows(card)
    mem, have_mem = build_compare_memory_chart(pool, card, rows)
    if have_mem:
        parts.append('<div class="rpt-mem-chart">\n<h4>Memory, as a multiple of what the samples need</h4>\n</div>')
        parts.append(_raw_html(mem))
        n = max(card["ns"])
        for arm, _b, _f in rows:
            names = (_mem_row(card, arm, n, WHY_CONFIG) or {}).get("device_borrowed_from")
            if names:
                parts.append(f'<p class="axis-note">{BORROWED_MARK} '
                             f'{pool.track(MEMORY_TABLE_LABELS.get(arm, arm_label(card, arm)))}: '
                             f'measured on {pool.track(" and ".join(names))}; the reading on this card '
                             "missed the pool the library reserves before the measurement's baseline, "
                             "and the pool's size does not depend on the card.</p>")
    honest, have_honest = build_landing_honest(pool, card)
    if have_honest:
        parts.append(_raw_html(honest))
    return "\n".join(parts)


def _cpu_panel(pool, slug, card):
    bw = Writer(pool)
    if not cpu_glance_block(pool, bw, slug, card):
        return ""
    return _raw_html(bw.text()) + f'\n<p class="axis-note perf-note">{GPU_ONLY_NOTE}</p>'


def _side_html(side, label, panels, slugs=None, radar=""):
    """One side's chips and device panels; ``panels``: [(chip label, html)].
    ``slugs`` tags each radio with its device (the page's shared device state
    reads it); ``radar`` is the side's radar block, placed under the panels."""
    out = [f'<div class="perf-side perf-side-{side}">']
    for i in range(len(panels)):
        slug = f' data-slug="{html.escape(slugs[i], quote=True)}"' if slugs else ""
        out.append(f'<input type="radio" name="perf-{side}" id="perf-{side}-{i}"{slug}'
                   f'{" checked" if i == 0 else ""}>')
    out.append(f'<div class="perf-chips" role="radiogroup" aria-label="{label}">')
    out += [f'<label for="perf-{side}-{i}">{chip}</label>' for i, (chip, _h) in enumerate(panels)]
    out.append("</div>")
    out += [f'<section class="perf-dev">\n{panel_html}\n</section>' for _chip, panel_html in panels]
    if radar:
        out.append(radar)
    out.append("</div>")
    return out


def build_perf_switch(pool, gpu_entries, cpu_entries, radars=None):
    """``_generated/perf_switch.md``: the whole "How it compares" block. The
    first device of each side in its preference list is the one shown; the
    anchor ``on-your-cpu`` selects the CPU side. ``radars`` ({side: radar
    block}) adds each side's radar under its device panels."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    sides = []
    for side, entries, pref, panel, chip in (
            ("gpu", gpu_entries, GPU_PREFERENCE, _gpu_panel, device_name),
            ("cpu", cpu_entries, CPU_PREFERENCE, _cpu_panel, cpu_tab_label)):
        shown = [(slug, card, panel_html) for slug, card in in_tab_order(entries, pref)
                 if (panel_html := panel(pool, slug, card))]
        panels = [(pool.track(chip(card)), panel_html) for _slug, card, panel_html in shown]
        if panels:
            sides.append((side, panels, [slug for slug, _c, _h in shown]))
    if not sides:
        return w.text(), False
    names = {"gpu": ("On a GPU", "GPU"), "cpu": ("On a CPU", "CPU")}
    lines = ['<div class="perf-switch">', '<span id="on-your-cpu"></span>']
    for i, (side, _p, _s) in enumerate(sides):
        lines.append(f'<input type="radio" name="perf-hw" id="perf-hw-{side}" data-side="{side}"'
                     f'{" checked" if i == 0 else ""}>')
    lines.append('<div class="perf-seg" role="radiogroup" aria-label="Hardware">')
    lines += [f'<label for="perf-hw-{side}">{names[side][0]}</label>' for side, _p, _s in sides]
    lines.append("</div>")
    for side, panels, slugs in sides:
        lines += _side_html(side, names[side][1] + " model", panels, slugs, (radars or {}).get(side, ""))
    lines.append('<script>(function(){var go=function(){if(location.hash==="#on-your-cpu"){'
                 'var r=document.getElementById("perf-hw-cpu");if(r)r.checked=true;}};go();'
                 'window.addEventListener("hashchange",go);})();</script>')
    lines.append("</div>")
    w.add("```{raw} html")
    radar_blocks = set((radars or {}).values())
    for line in lines:
        # the radar's geometry is not a measured figure: only the texts it
        # shows were tracked (by `build_radar`), never its coordinates
        (w.lines.append if line in radar_blocks else w.add)(line)
    w.add("```")
    return w.text(), True


def memory_info(pool, card, arm, n):
    """The info lines of one memory bar, from the card's memory row: arm,
    device, cell, what the driver accounted against the minimum, the card's
    stamp, and the borrowed-reading note when the reading is another card's."""
    row = _mem_row(card, arm, n, WHY_CONFIG) or {}
    lines = [_chart_label(card, arm), device_name(card),
             f"N = {n:,}, {_cfg_phrase(WHY_CONFIG['distribution'], WHY_CONFIG['max_steps'])}"]
    if row.get("device_peak_bytes") is not None and row.get("minimum_bytes"):
        lines.append(f"{_fmt_mib_int(row['device_peak_bytes'])} held by the process, against a "
                     f"minimum of {_fmt_mib_int(row['minimum_bytes'])}")
    lines.append(_card_stamp(card))
    if row.get("device_borrowed_from"):
        lines.append(f"{BORROWED_MARK} measured on {' and '.join(row['device_borrowed_from'])}; "
                     "the reading on this card missed the pool the library reserves "
                     "before the measurement's baseline")
    return [pool.track(x) for x in lines if x]


def build_compare_memory_chart(pool, card, rows):
    """``_generated/compare_memory_chart.md``: "Memory, as a multiple of what
    the samples need" -- the same `will_it_fit_rows` data compare.md's table
    already shows, as the mockup's linear HTML bars (lightest first, same
    row/track/fill markup as the time chart above)."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    n = max(card["ns"]) if card and card.get("ns") else None

    def label(arm):
        borrowed = (_mem_row(card, arm, n, WHY_CONFIG) or {}).get("device_borrowed_from")
        return _chart_label(card, arm) + (BORROWED_MARK if borrowed else "")

    factors = [f for _a, _b, f in rows if f is not None]
    if not rows or not factors:
        return w.text(), False
    aria = ", ".join(f"{label(arm)} {_fmt_ratio(factor)}"
                      for arm, _b, factor in rows if factor is not None)
    hi = max(factors) * MEM_BAR_HEADROOM
    w.add("```{raw} html")
    w.add(f'<div class="chart" role="img" '
          f'aria-label="Device memory as a multiple of the minimum: {aria}.">')
    for arm, _bytes, factor in rows:
        if factor is None:
            continue
        pct = 100 * factor / hi
        w.add(_bar_row_html(pool.track(label(arm)), ARM_CHIP_VAR.get(arm),
                             pct, pool.track(_fmt_ratio(factor)), arm.startswith("eagle"),
                             info=memory_info(pool, card, arm, n)))
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
    tie = dense_tie_line(perf_gpu, eagle_arm="eagle_simulate")
    if not wins or not tie:
        return w.text(), False
    rows, _n = will_it_fit_rows(perf_gpu)
    by_arm = {arm: factor for arm, _b, factor in rows}
    if not all(k in by_arm for k in ("eagle_graph", "warp_kernel", "eagle_simulate")):
        return w.text(), False
    steps_str = str(DENSE_CONFIG["max_steps"])
    device = device_name(perf_gpu)
    link = "https://amasat01.github.io/eagle/content/performance.html"

    w.add("```{raw} html")
    w.add('<div class="honest">')
    lead = (f"it is the fastest arm in {pool.track(str(wins[0]))} of the "
            f"{pool.track(str(wins[1]))} RK4 cells this card runs, and " if wins[0] else "")
    w.add(f"<p>NVIDIA Warp is an excellent per-thread kernel compiler: {lead}"
          f"when every sample runs all {pool.track(steps_str)} steps {dense_clause(pool, tie)}.</p>")
    lighter = by_arm["eagle_graph"] < by_arm["warp_kernel"]
    w.add(f"<p>On memory, hawk + eagle's lower-level building blocks "
          f"{'go lighter than Warp' if lighter else 'and Warp compare'}: "
          f"{pool.track(_fmt_ratio(by_arm['eagle_graph']))} the minimum against Warp's "
          f"{pool.track(_fmt_ratio(by_arm['warp_kernel']))}. eagle.simulate keeps room to "
          f"compact the batch and uses {pool.track(_fmt_ratio(by_arm['eagle_simulate']))}.</p>")
    w.add(f'<p class="fine">Measured on {pool.track(device)}. '
          f'<a href="{link}">Every number, every arm</a>.</p>')
    w.add("</div>")
    w.add("```")
    return w.text(), True




# --------------------------------------------------------------------------- #
# The fuller "fastest arm, every batch size" summary (replaces the 80-row
# perf_glance.md table on the landing index): one compact grid per GPU/CPU
# card, configuration x N, naming only the arm that WON each cell.
# --------------------------------------------------------------------------- #
def arm_display(card, arm):
    """The arm's label where several eagle arms stand side by side (the compare page, the fastest-arm
    grid): eagle's lower-level graph call is named as that, so its time is never read as eagle.simulate's."""
    if arm == "eagle_graph_auto":
        return "eagle auto, the lower-level call"
    return arm_label(card, arm)


def simulate_alongside(pool, card, n, cfg, best):
    """", eagle.simulate (the one-call API) X" when the fastest arm of the cell is another eagle arm and
    eagle.simulate ran the same cell: the cell's one eagle.simulate value, named, beside the fastest."""
    if best["arm"] == "eagle_simulate" or not best["arm"].startswith("eagle"):
        return ""
    row = _by_arm(_cell(card, n, cfg)).get("eagle_simulate")
    if not row:
        return ""
    return f"; eagle.simulate, the one-call API, {pool.track(_fmt_sig_time(_center(row['wall_s'])))}"


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
            cells.append(f"{arm_display(card, best['arm'])} ({pool.track(_fmt_sig_time(_center(best['wall_s'])))})")
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
def card_date_phrase(pool, card):
    """"NVIDIA H100 80GB HBM3, card of 2026-10-13": which device's card, and its own date, so a page
    that quotes cards run on different days says which day each number is from."""
    date = (card.get("generated_utc") or "")[:10]
    return pool.track(f"{device_name(card)}, card of {date}" if date else device_name(card))


def adaptive_host_note(pool, card):
    """One short line under the adaptive-ODE list: one host, the CPU arm's threads, PyTorch's fastest arm."""
    soft, method = card.get("software") or {}, card.get("method") or {}
    bits = [f"All arms ran in one host" + (f" ({soft['cpu']})" if soft.get("cpu") else "") + "."]
    threads = method.get("cpu_threads") or soft.get("omp_num_threads")
    if threads:
        bits.append(f"The CPU arm used {threads} threads.")
    bits.append("PyTorch is shown by its fastest arm on this card.")
    return pool.track(" ".join(bits))


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
                      f"({pool.track(arm_display(perf_gpu, best['arm']))}), "
                      f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))}"
                      f"{simulate_alongside(pool, perf_gpu, nn, WHY_CONFIG, best)}, of "
                      f"{pool.track(str(count))} arms run.")
            w.add("")
            # Hyphenated to match the built page's docutils-normalized id
            # (the MyST target label itself is written with underscores;
            # see build_measured_on's own comment for why a literal external
            # link must pre-normalize instead of relying on MyST's rewrite).
            w.add(f"[Full table, this card]({base}#perf-card-gpu-"
                  f"{pool.track(perf_gpu.get('device_slug', ''))}) ({card_date_phrase(pool, perf_gpu)}).")
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
              f"{pool.track(perf_gpu.get('device_slug', ''))}) ({card_date_phrase(pool, perf_gpu)}).")
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
                      f"({pool.track(arm_display(perf_gpu, best['arm']))}), "
                      f"{pool.track(_fmt_sig_time(_center(best['wall_s'])))}"
                      f"{simulate_alongside(pool, perf_gpu, small_n, cfg, best)}.")
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
                if (_mem_row(perf_gpu, arm, mem_n, WHY_CONFIG) or {}).get("device_borrowed_from"):
                    label += BORROWED_MARK
                w.add(f"| {pool.track(label)} | {pool.track(_fmt_mib_int(peak_bytes))} | "
                      f"{pool.track(_fmt_x(factor))} |")
            w.add("")
            w.add("Array libraries like CuPy, PyTorch and JAX keep a temporary for every operation in a "
                  "step, so their reservations stack up across the batch; hawk + eagle and NVIDIA Warp keep only "
                  "the per-sample state the workload itself needs. "
                  + memory_comparison_sentence(pool, sim_mem_row, warp_mem_row, graph_mem_row))
            w.add("")
            borrowed = [a for a in MEMORY_TABLE_ARMS
                        if (_mem_row(perf_gpu, a, mem_n, WHY_CONFIG) or {}).get("device_borrowed_from")]
            for a in borrowed:
                names = _mem_row(perf_gpu, a, mem_n, WHY_CONFIG)["device_borrowed_from"]
                w.add(f"{BORROWED_MARK} {pool.track(MEMORY_TABLE_LABELS.get(a, arm_label(perf_gpu, a)))}: "
                      f"measured on {pool.track(' and '.join(names))}. On "
                      f"{pool.track(device_name(perf_gpu))} the reading missed the memory pool the library "
                      "reserves during the warm-up, before the measurement's baseline; the pool's size does "
                      "not depend on the card, so the other cards' figure stands in until this card is "
                      "measured again.")
                w.add("")
            withheld = withheld_memory_arms(perf_gpu)
            if withheld:
                names = ", ".join(pool.track(MEMORY_TABLE_LABELS.get(a, arm_label(perf_gpu, a)))
                                  for a in withheld)
                w.add(f"Not shown: {names}. Its allocator reserves its memory pool during the warm-up, "
                      "before the baseline reading, so the reading after the run cannot see that pool "
                      "and falls below the state the workload needs. The figure returns once the "
                      "measurement takes its baseline before any library allocates.")
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
        w.add(adaptive_host_note(pool, rk78_gpu))
        w.add("")
        w.add(f"[Full table, this card]({base}#rk78-card-gpu-"
              f"{pool.track(rk78_gpu.get('device_slug', ''))}) ({card_date_phrase(pool, rk78_gpu)}).")
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
# The landing radar: where each tool shines, one radar per platform. Six majors on the
# landing radar, sixteen minors on the detailed one: seven minors measured from the
# committed cards (through the helpers above) and nine qualitative from
# `_data/radar_qualitative.json`. A minor's score = best value / this tool's value
# (1.0 = the edge); a major draws the mean of its minors. Pure functions first
# (testable on small dicts), then the markup. The device switch is the page's own
# `perf_switch`.
# --------------------------------------------------------------------------- #
RADAR_QUALITATIVE = pathlib.Path("_data") / "radar_qualitative.json"
#: Share of the radius where an axis's worst tool sits (never the centre), and
#: the ring fractions drawn: best, a geometric middle, worst.
RADAR_FLOOR = 0.2
RADAR_RINGS = (1.0, 0.6, RADAR_FLOOR)
#: The least spread (worst / best) an axis is stretched over: noise is not magnified.
RADAR_MIN_SPAN = 2.0
#: The minor axes, in the order the detailed radar draws them: grouped by major, the majors in the
#: order of `RADAR_MAJORS`. (key, label, kind, what it measures, where the number comes from).
#: kind "m" = measured from the cards, "q" = rubric in `_data/radar_qualitative.json`.
RADAR_AXES = (
    ("uneven", "Uneven ensembles", "m", "How long a batch takes when every sample stops at its own step, at the largest batch.",
     "performance card: results[].wall_s (spread stop steps)"),
    ("regular", "Regular ensembles", "m", "How long a batch takes when every sample runs the same number of steps, at the largest batch.",
     "performance card: results[].wall_s (uniform stop steps)"),
    ("small", "Small jobs", "m", "Wall time of the smallest batch, where launch overhead matters most.",
     "performance card: results[].wall_s at the smallest N (spread stop steps)"),
    ("adaptive", "Adaptive ODEs", "m", "Wall time of an adaptive-step orbit propagator (RK7(8)) at the largest batch.",
     "RK7(8) card: results[].wall_s"),
    ("memory", "Memory", "m", "Peak memory the process holds for the same workload (device memory on a GPU; host memory on a CPU at N = 1,000,000 only, net of the benchmark harness's own copies).",
     "performance card: memory.rows[] device_peak_bytes (GPU) or peak_bytes (CPU, net of the harness's copies)"),
    ("compile", "Compile time", "m", "Cold compile of the complex adaptive kernel (RK7(8) orbits) on empty caches; the simple oscillator's time and the growth factor are listed per tool. A tool with nothing to compile sits at the edge. Compiled once per kernel; raptor's compile does not depend on the problem size N.",
     "RK7(8) card: compile_time.rows[].cold_s (JAX: the largest-N row); a tool with no adaptive reading falls back, hollow, to the performance card's compile_time"),
    ("code", "Code size", "m", "Lines of code the task takes, non-blank and non-comment.",
     "performance card: code.arms[].lines"),
    ("tensor", "Tensor workloads (qualitative)", "q", "", "rubric"),
    ("array_style", "Array-style programming (qualitative)", "q", "", "rubric"),
    ("half_precision", "Half precision and below (qualitative)", "q", "", "rubric"),
    ("single_thread", "Single-thread abstraction (qualitative)", "q", "", "rubric"),
    ("differentiable", "Differentiable kernels (qualitative)", "q", "", "rubric"),
    ("control", "Low-level control (qualitative)", "q", "", "rubric"),
    ("arrays", "Works with your arrays (qualitative)", "q", "", "rubric"),
    ("deploy", "Deploy outside Python (qualitative)", "q", "", "rubric"),
    ("extensible", "Extensibility (qualitative)", "q", "", "rubric"),
)
#: The six majors of the landing radar and the minors each one draws the mean of. These groups were
#: fixed by theme before any data was looked at, and nothing here is tuned to a result: every minor counts
#: once, every major is the plain mean of its minors' radii, and the same function runs for every tool.
#: (key, label, kind, what it is, how it is drawn, minors). A major is "m" when its minors are measured
#: (each on its own best-to-worst log scale, floor `RADAR_FLOOR`) and "q" when they are rubric scores (linear).
RADAR_MAJORS = (
    ("ensemble", "Ensemble speed", "m",
     "How fast a batch of independent samples runs: uneven, regular, small and adaptive workloads.",
     "mean of four measured wall times, each on its own best-to-worst scale",
     ("uneven", "regular", "small", "adaptive")),
    ("footprint", "Footprint and turnaround", "m",
     "What the work costs around the run: the memory it holds, the time to compile and the code to write.",
     "mean of three measurements, each on its own best-to-worst scale",
     ("memory", "compile", "code")),
    ("numerics", "Tensors and precision (qualitative)", "q",
     "Dense tensor maths, array-style code and half precision: where PyTorch and JAX lead.",
     "mean of three rubric scores",
     ("tensor", "array_style", "half_precision")),
    ("authoring", "One-sample authoring (qualitative)", "q",
     "Writing the code for one sample and getting derivatives of it.",
     "mean of two rubric scores",
     ("single_thread", "differentiable")),
    ("lowlevel", "Low-level control (qualitative)", "q",
     "How much of the execution you control from the tool's own language.",
     "one rubric score",
     ("control",)),
    ("reach", "Reach (qualitative)", "q",
     "Where the tool fits in: your arrays, deployment outside Python and extension to new targets.",
     "mean of three rubric scores",
     ("arrays", "deploy", "extensible")),
)
RADAR_MAJOR_KEYS = tuple(m[0] for m in RADAR_MAJORS)
RADAR_MINORS_OF = {m[0]: m[5] for m in RADAR_MAJORS}
RADAR_MAJOR_OF = {minor: m[0] for m in RADAR_MAJORS for minor in m[5]}
#: Every axis the markup can draw, majors and minors, by key.
RADAR_MAJOR_AXES = tuple((m[0], m[1], m[2], m[3], m[4]) for m in RADAR_MAJORS)
RADAR_ALL_AXES = {a[0]: a for a in RADAR_AXES + RADAR_MAJOR_AXES}
#: Axes of each mode: the landing radar draws the majors, the detailed one every minor.
RADAR_MODE_KEYS = {"landing": RADAR_MAJOR_KEYS, "detailed": tuple(a[0] for a in RADAR_AXES)}
#: Drawn tools per side, in legend order, with their colour token; the
#: table-only tools follow (the detailed radar draws them too). raptor takes
#: --mark-eagle like the eagle bars.
RADAR_TOOLS = {
    "gpu": (("raptor", "--tool-raptor"), ("NVIDIA Warp", "--tool-warp"),
            ("JAX", "--tool-jax"), ("PyTorch", "--tool-pytorch")),
    "cpu": (("raptor", "--tool-raptor"), ("Numba", "--tool-numba"), ("JAX", "--tool-jax"),
            ("PyTorch", "--tool-pytorch"), ("NumPy", "--tool-numpy")),
}
RADAR_TABLE_ONLY = {"gpu": (("CuPy", "--tool-cupy"),), "cpu": ()}
#: Tools drawn but switched off until their legend chip is clicked (NumPy is far off every other tool on the CPU).
RADAR_DEFAULT_OFF = {"gpu": (), "cpu": ("NumPy",)}
#: Canvas of the SVG per mode (viewBox units): width, height, centre x, centre y, radius.
RADAR_GEOM = {"landing": (780, 720, 390, 355, 190), "detailed": (780, 650, 390, 325, 215)}

#: Per axis: the name drawn on the chart in the detailed mode ("short"), which
#: way is better ("dir"), the word at the edge end ("edge") and the unit of the
#: ring labels ("unit"). The landing radar draws the full name of the tensor axis.
RADAR_AXIS_EXTRA = {
    "uneven": {"short": "Uneven ensembles", "dir": "faster is better", "edge": "fastest", "unit": "time"},
    "regular": {"short": "Regular ensembles", "dir": "faster is better", "edge": "fastest", "unit": "time"},
    "small": {"short": "Small jobs", "dir": "faster is better", "edge": "fastest", "unit": "time"},
    "adaptive": {"short": "Adaptive ODEs", "dir": "faster is better", "edge": "fastest", "unit": "time"},
    "compile": {"short": "Compile time", "dir": "lower is better", "edge": "fastest", "unit": "time"},
    "memory": {"short": "Memory", "dir": "smaller is better", "edge": "smallest", "unit": "mem"},
    "code": {"short": "Code size", "dir": "smaller is better", "edge": "smallest", "unit": "lines"},
    "tensor": {"short": "Tensors", "dir": "", "edge": "", "unit": "rubric"},
    "array_style": {"short": "Array style", "dir": "", "edge": "", "unit": "rubric"},
    "half_precision": {"short": "Half precision", "dir": "", "edge": "", "unit": "rubric"},
    "control": {"short": "Control", "dir": "", "edge": "", "unit": "rubric"},
    "single_thread": {"short": "Single-thread", "dir": "", "edge": "", "unit": "rubric"},
    "differentiable": {"short": "Derivatives", "dir": "", "edge": "", "unit": "rubric"},
    "arrays": {"short": "Your arrays", "dir": "", "edge": "", "unit": "rubric"},
    "deploy": {"short": "Deploy", "dir": "", "edge": "", "unit": "rubric"},
    "extensible": {"short": "Extensibility", "dir": "", "edge": "", "unit": "rubric"},
    "ensemble": {"short": "Ensemble speed", "dir": "faster is better", "edge": "fastest", "unit": "mean"},
    "footprint": {"short": "Footprint", "dir": "lower is better", "edge": "lowest", "unit": "mean"},
    "numerics": {"short": "Tensors and precision", "dir": "", "edge": "", "unit": "rubric"},
    "authoring": {"short": "One-sample authoring", "dir": "", "edge": "", "unit": "rubric"},
    "lowlevel": {"short": "Low-level control", "dir": "", "edge": "", "unit": "rubric"},
    "reach": {"short": "Reach", "dir": "", "edge": "", "unit": "rubric"},
}
RADAR_NOTE = ("Every measured axis is the per-sample ensemble workload raptor is built for; dense tensor maths, training "
              "and half precision are the qualitative axes, where PyTorch and JAX lead. Outer is better; overlaps are "
              "complementary, not a ranking.")
RADAR_HOVER_HINT = "Each axis is defined in the list below the chart; hover or tap one for the numbers behind it."
RADAR_DETAILED_NOTE = RADAR_NOTE
RADAR_CONTROL_CAPTION = ("NVIDIA Warp gives you near-total control of every kernel, short of raw CUDA. raptor hands that "
                         "control to the engine on purpose, so compaction and the launch shape are decided at run time; "
                         "the two are different trade-offs, not a ranking.")
RADAR_MAJOR_RULE = ("Each of the six majors is the plain mean of its minor axes (the detailed radar draws every minor), "
                    "with equal weights and the same rule for every tool; a minor a tool has no reading on is left out of "
                    "its mean and the major's marker is drawn hollow. Hover or tap a major to see its minors.")
RADAR_SCALE_RULE = ("Each measured axis is stretched over its own best-to-worst range, so ring labels differ per axis "
                    "(compile time: fixed, 0.1 s to 100 s; code size: at least 4x). Axes are grouped by theme, "
                    "so read the axes, not the area.")
RADAR_QUAL_RULE = ("Italic axes are the author's judgement, not measurements: hollow markers, a linear scale, and no marker "
                   "where a tool has no reading. A hollow marker on a measured axis means a minor is missing or, for compile "
                   "time, is the tool's simple-kernel time. The hover panel has each axis's full wording.")


def radar_tool(arm, kind):
    """The tool an arm belongs to on a `kind` ("gpu" | "cpu") card, or None for
    an arm the radar does not weigh (eager loops, plain Python, the host arm of a
    GPU card). eagle arms are raptor (eagle + hawk)."""
    if arm.startswith("eagle"):
        return None if (kind == "gpu" and arm.startswith("eagle_cpu")) else "raptor"
    if kind == "gpu":
        if arm.startswith("torch_"):
            return "PyTorch"
        return {"warp_kernel": "NVIDIA Warp", "jax_vmap": "JAX", "cupy_masked": "CuPy"}.get(arm)
    return {"numba_prange": "Numba", "jax_shard8": "JAX", "jax_vmap": "JAX",
            "torch_masked": "PyTorch", "numpy_masked": "NumPy", "mp_numpy": "NumPy"}.get(arm)


def best_arm_per_tool(values, kind):
    """{tool: (arm, value)}: each tool's best (smallest positive) arm among
    ``values`` ({arm: value})."""
    best = {}
    for arm, v in values.items():
        tool = radar_tool(arm, kind)
        if tool is None or v is None or not v > 0:
            continue
        if tool not in best or v < best[tool][1]:
            best[tool] = (arm, v)
    return best


def radar_scores(best):
    """{tool: best value / tool value} from `best_arm_per_tool`'s output
    (1.0 for the best tool)."""
    if not best:
        return {}
    floor = min(v for _arm, v in best.values())
    return {tool: floor / v for tool, (_arm, v) in best.items()}


#: Axes whose values sit close together stretch over a wider minimum span: code size runs
#: from ~22 to ~44 lines, and a 22-vs-32-line pair should stay near the edge (0.78 of it).
RADAR_MIN_SPAN_BY_AXIS = {"code": 4.0}
#: Compile time is the exception: a FIXED absolute log scale, the same on every device,
#: 0.1 s at the edge to 100 s at the floor. Bands drawn on hover: (seconds, label).
RADAR_COMPILE_EDGE_S, RADAR_COMPILE_FLOOR_S = 0.1, 100.0
RADAR_COMPILE_BANDS = ((1.0, "under 1 s: instant"), (10.0, "1-10 s: noticeable"), (60.0, "over 60 s: breaks interactive use"))


def radar_axis_span(ratios, minimum=RADAR_MIN_SPAN):
    """Worst / best over the finite ratios (each >= 1), at least ``minimum``."""
    finite = [r for r in ratios if math.isfinite(r)]
    return max(max(finite, default=1.0), minimum)


def radar_radius(ratio, span):
    """Fraction of the radius for a tool whose value is ``ratio`` x the axis's
    best (1 = best, inf = not run): log between the best (edge, 1.0) and
    ``span`` (RADAR_FLOOR); beyond the span or infinite, the floor."""
    if not math.isfinite(ratio) or ratio >= span:
        return RADAR_FLOOR
    return 1.0 - (1.0 - RADAR_FLOOR) * math.log(max(ratio, 1.0)) / math.log(span)


def radar_radius_compile(seconds):
    """Radius fraction on the fixed compile scale: log, 0.1 s at the edge (1.0)
    to 100 s at the floor (0.2); faster than the edge clamps to the edge."""
    lo, hi = RADAR_COMPILE_EDGE_S, RADAR_COMPILE_FLOOR_S
    if seconds <= lo:
        return 1.0
    if seconds >= hi:
        return RADAR_FLOOR
    return 1.0 - (1.0 - RADAR_FLOOR) * math.log(seconds / lo) / math.log(hi / lo)


def radar_compile_band(seconds):
    """How a compile time reads to someone waiting on it."""
    if seconds < 1:
        return "under 1 s: instant"
    if seconds < 10:
        return "1-10 s: noticeable"
    if seconds < 60:
        return "10-60 s: long"
    return "over 60 s: breaks interactive use"


def radar_compile_rings():
    """Hover ring labels of the fixed scale: edge, geometric middle, floor."""
    mid = math.sqrt(RADAR_COMPILE_EDGE_S * RADAR_COMPILE_FLOOR_S)
    return " · ".join((f"{v:.2g} s" if v < 99 else f"{v:.0f} s") for v in (RADAR_COMPILE_EDGE_S, mid, RADAR_COMPILE_FLOOR_S))


def radar_radius_rubric(score, lo, hi):
    """Linear radius for a rubric score: ``lo`` at the floor, ``hi`` at the edge."""
    return RADAR_FLOOR + (1.0 - RADAR_FLOOR) * (score - lo) / (hi - lo)


def radar_ring_labels(span):
    """The three ring labels of a measured axis, best first: "best · 3.1× · 9.9×"
    (best, the geometric middle, the axis's worst)."""
    return " · ".join(("best", _fmt_ratio(math.sqrt(span)), _fmt_ratio(span)))


def radar_ring_units(unit, best, span, fmt_mem):
    """Ring labels of a measured axis in its own units, from the edge inwards:
    the best value, the geometric middle and the worst the axis spans
    ("285 ms · 750 ms · 1.95 s", "50 · 69 · 128 MiB", "22 · 31 · 44 lines")."""
    values = [best, best * math.sqrt(span), best * span]
    if unit == "time":
        return " · ".join(_fmt_sig_time(v) for v in values)
    if unit == "mem":
        texts = [fmt_mem(v) for v in values]
        return " · ".join([t.replace(" MiB", "") for t in texts[:2]] + texts[2:])
    return " · ".join(f"{round(v)}" for v in values) + " lines"


def _fmt_score(score):
    """A 0..1 score at two significant figures, floored like every ratio."""
    f = _round_sig_floor(score)
    if f is None:
        return "0"
    return f"{f:.{max(0, 1 - math.floor(math.log10(f)))}f}"


def _radar_wall_values(card, n, cfg):
    """{arm: wall s} of one cell. eagle is read by its headline arm (eagle.simulate) when the cell has
    it, so the radar quotes the same value as the bars; the other eagle arms stay on the card pages."""
    walls = {r["arm"]: _center(r["wall_s"]) for r in _cell(card, n, cfg)}
    if "eagle_simulate" in walls:
        walls = {a: v for a, v in walls.items() if not a.startswith("eagle") or a == "eagle_simulate"}
    return walls


def _rk78_wall_values(card):
    n = max(card["ns"])
    return n, {r["arm"]: _center(r["wall_s"]) for r in card.get("results", []) if r["n"] == n}


def _compile_values(card, n):
    """{arm: (cold s, warm s)} from the card's ``compile_time`` rows. Cold =
    a fresh process on empty caches, warm = a fresh process on the caches the
    cold run filled; each the median of 3 processes, the timer spanning the
    first call to a ready kernel (the card's compile ``method``). Per-N rows
    (key ``jax:1000`` ...) are read at ``n``; an arm in the card's ``shared``
    map reuses another arm's row; arms in ``none`` have no compile step and
    carry no reading."""
    ct = card.get("compile_time") or {}
    out = {}
    for row in ct.get("rows", []):
        key = row.get("key", "")
        suffix = key.rsplit(":", 1)[-1]
        if ":" in key and suffix.isdigit() and int(suffix) != n:
            continue
        arms = row.get("arms") or ([row["arm"]] if "arm" in row else [])
        for arm in arms:
            out[arm] = (row["cold_s"]["median"], row["warm_s"]["median"])
    for arm, target in (ct.get("shared") or {}).items():
        if target in out:
            out.setdefault(arm, out[target])
    return out


def _memory_values(card, n, kind):
    """{arm: bytes}: GPU = ``device_peak_bytes`` (the memory the CUDA driver
    accounts to the process after the run minus before it, i.e. the
    allocator's high-water reservation; withheld readings are None); CPU =
    ``peak_bytes`` (peak resident set above the baseline) net of the
    benchmark harness's own copies (`net_peak_bytes`)."""
    field = "device_peak_bytes" if kind == "gpu" else "peak_bytes"
    out = {}
    for arm in arm_keys(card):
        row = _mem_row(card, arm, n, WHY_CONFIG)
        if row and row.get(field):
            value = row[field] if kind == "gpu" else published_peak_bytes(row, card["memory"]["rows"])
            if value:
                out[arm] = value
    return out


def _code_values(card):
    return {arm: arm_line_count(card, arm) for arm in arm_keys(card)}


def _cpu_model_key(card):
    """A CPU card's model as a join key (the perf and rk78 CPU cards spell
    it differently: a dict with 'model' or a plain string)."""
    cpu = card.get("cpu")
    model = cpu.get("model") if isinstance(cpu, dict) else cpu
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\((r|tm)\)", "", (model or "").lower()))


def pair_rk78(entries, rk78_entries, kind):
    """{slug: rk78 card or None} for the perf cards ``entries``: GPU cards pair
    by device slug, CPU cards by CPU model."""
    out = {}
    for slug, card in entries:
        match = None
        for rslug, rcard in rk78_entries:
            if (kind == "gpu" and rslug == slug) or (kind == "cpu" and _cpu_model_key(rcard) == _cpu_model_key(card)):
                match = rcard
        out[slug] = match
    return out


def uneven_by_tool(card, kind):
    """{tool: (arm, wall)} on the uneven-ensemble cell (largest N)."""
    if not card or not card.get("ns"):
        return {}
    return best_arm_per_tool(_radar_wall_values(card, max(card["ns"]), WHY_CONFIG), kind)


def load_qualitative(pool, path=None):
    """The rubric axes: ``{"axes": {key: {"label", "rubric", "scale": [lo, hi],
    "scores": {tool: {"score", "reason"}}}}}``, recorded in SOURCES.json by md5."""
    if path is None:
        p = pool.site_source(RADAR_QUALITATIVE)
    else:
        p = pathlib.Path(path)
    return json.loads(p.read_text())


def _compile_entries(perf, rk78, kind, n_max):
    """{tool: {"value" s|None, "arm", "text", "detail", "hollow"}} for the compile axis.
    The value is the COMPLEX kernel's cold compile (rk78 card, largest-N row for the
    per-shape arms); the simple oscillator's time and the growth factor go in the
    detail. A tool with no complex reading falls back to its simple-kernel reading,
    drawn hollow and labelled. "No compile step" only for a tool with genuinely none
    (never PyTorch: its torch.compile arm is the apples-to-apples one)."""
    simple_all = _compile_values(perf, n_max)
    simple = best_arm_per_tool({a: v[0] for a, v in simple_all.items()}, kind)
    complex_best, complex_all = {}, {}
    if rk78 and rk78.get("ns") and rk78.get("compile_time"):
        complex_all = _compile_values(rk78, max(rk78["ns"]))
        complex_best = best_arm_per_tool({a: v[0] for a, v in complex_all.items()}, kind)
    out = {}
    for tool in set(simple) | set(complex_best):
        if tool in complex_best:
            arm, v = complex_best[tool]
            bits = [f"warm {_fmt_sig_time(complex_all[arm][1])}"]
            if tool in simple:
                sv = simple[tool][1]
                bits.insert(0, f"simple kernel {_fmt_sig_time(sv)}, {_fmt_ratio(v / sv)} from the simple to the adaptive kernel")
            if tool == "JAX":
                bits.append("JAX recompiles for every shape; the largest-N row is shown")
            out[tool] = {"value": v, "arm": arm_label(rk78, arm), "text": _fmt_sig_time(v), "detail": " · ".join(bits), "hollow": False}
        else:
            arm, v = simple[tool]
            why = ("the adaptive card has no torch.compile arm" if tool == "PyTorch"
                   else "this device has no adaptive-kernel compile reading")
            out[tool] = {"value": v, "arm": arm_label(perf, arm), "text": _fmt_sig_time(v),
                         "detail": f"simple kernel only: {why} · warm {_fmt_sig_time(simple_all[arm][1])}", "hollow": True}
    for arm in (perf.get("compile_time") or {}).get("none") or []:
        tool = radar_tool(arm, kind)
        if tool is not None and tool != "PyTorch" and tool not in out and arm in arm_keys(perf):
            out[tool] = {"value": None, "arm": arm_label(perf, arm), "text": "no compile step", "detail": "", "hollow": False}
    return out


def _device_axes(perf, rk78, kind):
    """Per measured axis: ``({tool: {"value": number|None, "arm": str, "text":
    str, "detail": str}}, description of the cell)``. ``value`` None = the tool
    has no compile step (compile axis only: it sits at the edge). A tool with
    no reading is absent from the axis (no vertex), never 0."""
    axes = {}
    n_max, n_min = max(perf["ns"]), min(perf["ns"])
    for key, n, cfg in (("uneven", n_max, WHY_CONFIG), ("regular", n_max, DENSE_CONFIG),
                        ("small", n_min, WHY_CONFIG)):
        best = best_arm_per_tool(_radar_wall_values(perf, n, cfg), kind)
        axes[key] = ({t: {"value": v, "arm": a, "text": _fmt_sig_time(v), "detail": ""} for t, (a, v) in best.items()},
                     f"N = {n:,}, {_cfg_phrase(cfg['distribution'], cfg['max_steps'])}")
    if rk78 and rk78.get("ns"):
        n, vals = _rk78_wall_values(rk78)
        best = best_arm_per_tool(vals, kind)
        axes["adaptive"] = ({t: {"value": v, "arm": a, "text": _fmt_sig_time(v), "detail": ""} for t, (a, v) in best.items()},
                            f"adaptive RK7(8) orbits, N = {n:,}")
    else:
        axes["adaptive"] = ({}, "no adaptive-ODE card for this device")
    axes["compile"] = (_compile_entries(perf, rk78, kind, n_max),
                       "fixed scale: 0.1 s at the edge, 100 s at the floor")
    mem = _memory_values(perf, n_max, kind)
    fmt = _fmt_mib_int if kind == "gpu" else _fmt_mib
    best = best_arm_per_tool(mem, kind)
    axes["memory"] = ({t: {"value": v, "arm": a, "text": fmt(v), "detail": ""} for t, (a, v) in best.items()},
                      f"{'device' if kind == 'gpu' else 'host'} memory, N = {n_max:,}, "
                      f"{_cfg_phrase(WHY_CONFIG['distribution'], WHY_CONFIG['max_steps'])}")
    best = best_arm_per_tool(_code_values(perf), kind)
    axes["code"] = ({t: {"value": v, "arm": a, "text": f"{v} lines", "detail": ""} for t, (a, v) in best.items()},
                    "lines of code, non-blank and non-comment; the scale spans at least 4x from best to worst, "
                    "so a few lines of difference are not magnified")
    return axes


def _stretch(entries, minimum=RADAR_MIN_SPAN):
    """Fill ``ratio`` (value / best, >= 1; inf = not run), ``r`` and ``score``
    for a measured axis's entries ({tool: {"rv": raw ratio or None for the
    edge}}) and return the ring labels. A raw ratio is normalised by the best."""
    finite = [e["rv"] for e in entries.values() if e["rv"] is not None and math.isfinite(e["rv"])]
    floor = min(finite, default=1.0)
    for e in entries.values():
        rv = e.pop("rv")
        ratio = 1.0 if rv is None else (rv / floor if math.isfinite(rv) else math.inf)
        e["ratio_f"] = ratio
    span = radar_axis_span([e["ratio_f"] for e in entries.values()], minimum)
    for e in entries.values():
        e["r"] = radar_radius(e["ratio_f"], span)
        e["score"] = 0.0 if not math.isfinite(e["ratio_f"]) else 1.0 / e["ratio_f"]
    return span


def radar_minor_axes(side, perf, rk78, qualitative):
    """One device's minor axes, as plain data: ``{key: {"desc", "rl", "tools":
    {tool: {"score", "r", "value", "ratio", "arm", "detail"}}}}`` for every tool of
    the side (drawn and table-only). A tool with no reading on an axis is absent
    from it (no vertex), never 0. Measured axes are stretched over their own
    best..worst (see `radar_radius`); rubric axes are linear."""
    raw = _device_axes(perf, rk78, side)
    tools = [t for t, _c in RADAR_TOOLS[side] + RADAR_TABLE_ONLY[side]]
    axes = {}
    for key, _label, kind, _what, _src in RADAR_AXES:
        entry, rl, desc = {}, "", ""
        if kind == "q":
            qa = qualitative["axes"][key]
            lo, hi = qa.get("scale", [1, 5])
            desc = qa["rubric"]
            rl = " · ".join(str(x) for x in (hi, (lo + hi) // 2, lo))
            scores = {**(qa.get("scores") or {}), **(qa.get("scores_cpu") or {} if side == "cpu" else {})}
            for tool in tools:
                q = scores.get(tool)
                if q:
                    entry[tool] = {"score": q["score"] / hi, "r": radar_radius_rubric(q["score"], lo, hi),
                                   "value": f"{q['score']} of {hi}", "ratio": q.get("reason", ""),
                                   "arm": "rubric", "detail": "", "pts": q["score"]}
        elif key == "compile":
            vals, desc = raw[key]
            rl = radar_compile_rings()
            for tool in tools:
                v = vals.get(tool)
                if v is None:
                    continue
                sec = v["value"]
                entry[tool] = {"score": 1.0 if sec is None else min(1.0, RADAR_COMPILE_EDGE_S / sec),
                               "r": 1.0 if sec is None else radar_radius_compile(sec), "value": v["text"],
                               "ratio": "nothing to compile" if sec is None else radar_compile_band(sec),
                               "arm": v["arm"], "detail": v["detail"], "hollow": v["hollow"]}
            secs = [vals[t]["value"] for t in entry if vals[t]["value"]]
            for tool, e in entry.items():
                sec = vals[tool]["value"]
                e["x"] = 1.0 if not sec else sec / min(secs)
        else:
            vals, desc = raw[key]
            for tool in tools:
                v = vals.get(tool)
                if v is None:
                    continue
                entry[tool] = {"rv": v["value"], "arm": v["arm"] if v["value"] is None else
                               arm_label(rk78 if key == "adaptive" else perf, v["arm"]),
                               "detail": v["detail"], "value": v["text"]}
            best_v = min((e["rv"] for e in entry.values() if e["rv"] is not None and math.isfinite(e["rv"])), default=None)
            span = _stretch(entry, RADAR_MIN_SPAN_BY_AXIS.get(key, RADAR_MIN_SPAN))
            unit = RADAR_AXIS_EXTRA[key]["unit"]
            if best_v is not None and unit in ("time", "mem", "lines"):
                rl = radar_ring_units(unit, best_v, span, _fmt_mib_int if side == "gpu" else _fmt_mib)
            else:
                rl = radar_ring_labels(span)
            for e in entry.values():
                e["x"] = e["ratio_f"]
                e["ratio"] = ("nothing to compile" if e["value"] == "no compile step"
                              else f"{_fmt_ratio(e.pop('ratio_f'))} the best")
        axes[key] = {"desc": desc, "rl": rl, "tools": entry}
    return axes


#: The measured feature behind the "Batches that thin out" sector of the rosette.
DIVERGENCE_KEYS = ("uneven_eff",)


def divergence_features(pool, side, card):
    """``{feature: {"tools": {tool: entry}}}`` for the uneven-batch efficiency of one
    card, in the shape of a minor axis (``value``, ``ratio``, ``arm``, ``detail``, ``x`` = the ratio to the best,
    inf when the tool has no saving). A feature with no reading on the card (no reference measurement yet) has
    no tools."""
    out = {k: {"tools": {}} for k in DIVERGENCE_KEYS}
    if not card or not card.get("ns"):
        return out
    got = eff_values(pool, side, card)
    vals = got[2] if got else []
    top = max((v["fraction"] for _a, _l, v in vals), default=0.0)
    for arm, _label, v in vals:
        tool = radar_tool(arm, side)
        if tool is None:
            continue
        out["uneven_eff"]["tools"][tool] = {
            "value": _fmt_eff(v["fraction"]), "arm": arm_label(card, arm), "x": top / v["fraction"],
            "ratio": ("1.0\u00d7 the best" if v["fraction"] == top else f"{_fmt_ratio(top / v['fraction'])} the best"),
            "detail": f"{_fmt_rate(v['spread'])} of {_fmt_rate(v['sol'])} sample-steps per second"}
    return out


def radar_major_entry(minors):
    """One tool's entry on a major, from its minors' entries (``minors``: {minor key: entry}, in the
    major's order; a minor the tool has no reading on is simply absent). The radius is the plain
    arithmetic mean of the minors' radii that are present (a missing minor is left out of the mean,
    never counted as 0), the score the mean of their scores. None when no minor has a reading."""
    if not minors:
        return None
    r = sum(e["r"] for e in minors.values()) / len(minors)
    score = sum(e["score"] for e in minors.values()) / len(minors)
    return {"r": r, "score": score, "minors": minors}


def radar_majors(minor_axes, scale=(1, 5)):
    """{major key: {"desc", "rl", "tools": {tool: entry}}} from `radar_minor_axes`' output. Each tool's
    entry is `radar_major_entry` over its present minors plus the texts the tooltip and the table read:
    ``value`` (the mean, in the major's own terms), ``ratio`` (how many minors it rests on),
    ``arm``, ``detail`` (the minors it has no reading on) and ``missing``. The marker is ``hollow`` for
    a rubric major, when any minor is missing and when a minor itself is hollow. ``scale`` is the rubric's
    (lowest, highest) score."""
    out = {}
    for key, _label, kind, what, how, minor_keys in RADAR_MAJORS:
        tools, seen = {}, []
        for k in minor_keys:
            seen += [t for t in minor_axes[k]["tools"] if t not in seen]
        for tool in seen:
            present = {k: minor_axes[k]["tools"][tool] for k in minor_keys if tool in minor_axes[k]["tools"]}
            e = radar_major_entry(present)
            missing = [k for k in minor_keys if k not in present]
            names = [RADAR_ALL_AXES[k][1].replace(" (qualitative)", "") for k in missing]
            e["hollow"] = kind == "q" or bool(missing) or any(m.get("hollow") for m in present.values())
            e["missing"] = missing
            if kind == "q":
                lo, hi = scale
                e["value"] = f"{lo + (e['r'] - RADAR_FLOOR) / (1.0 - RADAR_FLOOR) * (hi - lo):.1f} of {hi}"
            else:
                e["value"] = f"{e['r']:.2f} of the radius"
            e["ratio"] = (f"mean of {len(present)} of {len(minor_keys)}" if missing else
                          f"mean of {len(minor_keys)}" if len(minor_keys) > 1 else "one rubric score")
            e["arm"] = "rubric" if kind == "q" else "mean of the minors"
            e["detail"] = ("no reading on " + ", ".join(names)) if missing else ""
            tools[tool] = e
        out[key] = {"desc": how, "rl": (f"{scale[1]} · {(scale[0] + scale[1]) // 2} · {scale[0]}" if kind == "q"
                                        else "best · in between · worst"), "tools": tools}
    return out


def build_radar_device(side, slug, perf, rk78, qualitative, mode="landing"):
    """One device's radar, as plain data: ``{"slug", "name", "card", "link", "axes"}``;
    ``axes`` are the six majors in the landing mode (each tool's entry carries the minors it is the
    mean of) and the sixteen minors in the detailed mode."""
    minor_axes = radar_minor_axes(side, perf, rk78, qualitative)
    axes = radar_majors(minor_axes) if mode == "landing" else minor_axes
    return {"slug": slug, "name": _tab_device(perf), "card": f"{_tab_device(perf)}, {_card_stamp(perf)}",
            "link": _card_link(side, slug), "axes": axes,
            "minor_axes": minor_axes}


def _card_link(side, slug):
    family = "perf_gpu" if side == "gpu" else "perf_cpu"
    return f"{EAGLE_PERF_PAGE}#{EAGLE_ANCHOR_FAMILY[family]}-{slug}".replace("_", "-")


def radar_devices(side, entries, rk78_entries, qualitative, mode="landing"):
    """[(slug, radar device)] for the side's cards in tab order."""
    pref = GPU_PREFERENCE if side == "gpu" else CPU_PREFERENCE
    paired = pair_rk78(entries, rk78_entries, side)
    return [(slug, build_radar_device(side, slug, card, paired[slug], qualitative, mode))
            for slug, card in in_tab_order([e for e in entries if e[1].get("ns")], pref)]


# ---- markup ---------------------------------------------------------------- #
#: Axis order of each radar kind: the order of `RADAR_MODE_KEYS`, which the major structure fixes (the
#: detailed radar draws the minors grouped by major, majors in the landing order).
RADAR_ORDER = {mode: list(keys) for mode, keys in RADAR_MODE_KEYS.items()}


def _axes_of(mode):
    return [RADAR_ALL_AXES[k] for k in RADAR_ORDER[mode]]


def _axis_angle(i, n, mode="landing"):
    """Angle of axis ``i`` (radians, 0 = right, clockwise): every axis of every radar
    evenly spaced around the ring from the top, no gap and no divider."""
    return -math.pi / 2 + 2 * math.pi * i / n


def radar_xy(i, r, mode="landing"):
    """Point of axis ``i`` at radius fraction ``r``, one decimal."""
    _w, _h, cx, cy, big_r = RADAR_GEOM[mode]
    a = _axis_angle(i, len(RADAR_MODE_KEYS[mode]), mode)
    return (round(cx + big_r * r * math.cos(a), 1), round(cy + big_r * r * math.sin(a), 1))


#: Icon edge in viewBox units: beside a label (landing, detailed) and on the disc of a phone-width radar.
RADAR_ICON_SIZE = {"landing": 22, "detailed": 22, "disc": 28}
RADAR_ICON_GAP = 6


def _icon_id(ids, key):
    return f"rico-{ids}-{key}" if ids else f"rico-{key}"


def _icon_aria(key):
    """Full axis name and which way is better, for the icon that stands in for the label on a phone."""
    name = RADAR_ALL_AXES[key][1]
    name = name[: -len(" (qualitative)")] if name.endswith(" (qualitative)") else name
    d = RADAR_AXIS_EXTRA[key]["dir"]
    return f"{name}, {d}" if d else f"{name} (qualitative), a higher score is better"


def _icon_symbols(ids, mode):
    """The hidden ``<symbol>`` sheet the radar's icons are drawn from (inline, no external files)."""
    keys = list(RADAR_MODE_KEYS[mode]) + ([a[0] for a in RADAR_AXES] if mode == "landing" else [])   # the fan draws the minors too
    syms = "".join(f'<symbol id="{_icon_id(ids, k)}" viewBox="0 0 24 24">{radar_icons.ICONS[k]}</symbol>' for k in keys)
    return f'<svg class="radar-icons" width="0" height="0" aria-hidden="true" focusable="false"><defs>{syms}</defs></svg>'


def axis_display(key, mode):
    """The name drawn on the chart: short in the detailed mode, the full name
    (without the "(qualitative)" suffix, which gets its own line) otherwise."""
    if mode == "detailed":
        return RADAR_AXIS_EXTRA[key]["short"]
    label = RADAR_ALL_AXES[key][1]
    return label[: -len(" (qualitative)")] if label.endswith(" (qualitative)") else label


def _name_lines(name, wrap=16):
    words = name.split()
    if len(name) > wrap and len(words) > 1:
        k = min(range(1, len(words)), key=lambda j: abs(len(" ".join(words[:j])) - len(" ".join(words[j:]))))
        return [" ".join(words[:k]), " ".join(words[k:])]
    return [name]


def _label_rows(key, kind, mode):
    """[(text, css class, size)] of an axis label at rest: the name (largest) and
    under it the direction. The edge word and the ring units appear on hover."""
    fs, fd = 16, 13                       # one type scale on every radar
    rows = [(t, "radar-name", fs) for t in _name_lines(axis_display(key, mode), 16 if mode == "landing" else 11)]
    # the detailed radar's 17 names get no second line (the direction is in its panel and axis list)
    if RADAR_AXIS_EXTRA[key]["dir"] and mode == "landing":
        rows.append((RADAR_AXIS_EXTRA[key]["dir"], "radar-dir", fd))
    elif mode == "landing" and kind == "q":
        rows.append(("(qualitative)", "radar-dir", fd))
    return rows


def _axis_label_svg(i, n, key, kind, mode, ids=""):
    """The axis label at rest: name, then direction, anchored away from the chart.
    An icon on the disc stands in for it on a narrow column."""
    _w, _h, cx, cy, big_r = RADAR_GEOM[mode]
    a = _axis_angle(i, n, mode)
    ca, sa = math.cos(a), math.sin(a)
    lr = big_r + 24
    lx, ly = cx + lr * ca, cy + lr * sa
    anchor = "start" if ca > 0.1 else ("end" if ca < -0.1 else "middle")
    rows = _label_rows(key, kind, mode)
    heights = [r[2] + 4 for r in rows]
    total = sum(heights)
    isz = RADAR_ICON_SIZE[mode]
    shift = {"start": isz + RADAR_ICON_GAP, "middle": (isz + RADAR_ICON_GAP) / 2, "end": 0}[anchor]
    lx_text = lx + shift
    if sa < -0.5:
        y = ly - total + heights[0]
    elif sa > 0.9:                      # only the labels at the very bottom hang below their axis
        y = ly + heights[0]
    else:
        y = ly - total / 2 + heights[0]
    spans = []
    y_top = y - rows[0][2] * 0.8
    for text, cls, size in rows:
        spans.append(f'<tspan class="{cls}" x="{lx_text:.1f}" y="{y:.1f}">{html.escape(text)}</tspan>')
        y += size + 4
    y_mid = (y_top + (y - size - 4 + size * 1.2)) / 2          # centre of the label block
    full = RADAR_ALL_AXES[key][1]
    cls = "radar-axis q" if kind == "q" else "radar-axis"
    est = max(len(r[0]) * r[2] * 0.56 for r in rows)            # the script measures the real width
    ix = {"start": lx, "middle": lx - (isz + RADAR_ICON_GAP + est) / 2, "end": lx - est - RADAR_ICON_GAP - isz}[anchor]
    wide = (f'<g class="radar-icon wide" aria-hidden="true" data-axis="{key}" data-lx="{lx:.1f}" data-anchor="{anchor}" '
            f'data-y="{y_mid:.1f}" transform="translate({ix:.1f} {y_mid - isz / 2:.1f})">'
            f'<use href="#{_icon_id(ids, key)}" width="{isz}" height="{isz}"/></g>')
    feat = f' data-feature="{key}"' if mode == "detailed" else ""
    out = (wide + f'<text class="{cls}" data-axis="{key}"{feat} text-anchor="{anchor}" tabindex="0" role="button" '
           f'aria-label="{html.escape(full)}: explain this axis">{"".join(spans)}</text>')
    nr = big_r + 26                                             # the disc icon sits just outside the tick
    ds = RADAR_ICON_SIZE["disc"]
    disc = (f'<g class="radar-icon disc" role="button" tabindex="0" data-axis="{key}" aria-label="{html.escape(_icon_aria(key))}" '
            f'transform="translate({cx + nr * ca - ds / 2:.1f} {cy + nr * sa - ds / 2:.1f})">'
            f'<circle class="hit" cx="{ds / 2}" cy="{ds / 2}" r="{ds * 0.62:.1f}"/>'
            f'<use href="#{_icon_id(ids, key)}" width="{ds}" height="{ds}"/></g>')
    return out + disc


def radar_static_svg(device, tools, aria, mode, off=(), ids=""):
    """The SVG for one device. The tool shapes and the ring labels are what
    the script redraws on a device switch; the rings, spokes and axis names are
    the same for every device."""
    w, h, cx, cy, big_r = RADAR_GEOM[mode]
    axes = _axes_of(mode)
    n = len(axes)
    parts = [f'<svg class="radar-svg" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(aria, quote=True)}">']
    for r in RADAR_RINGS:
        pts = " ".join("%.1f,%.1f" % radar_xy(i, r, mode) for i in range(n))
        parts.append(f'<polygon class="radar-ring" points="{pts}"/>')
    for i, (key, _l, kind, _w2, _s) in enumerate(axes):
        x, y = radar_xy(i, 1.0, mode)
        parts.append(f'<line class="radar-spoke" x1="{cx}" y1="{cy}" x2="{x}" y2="{y}"/>')
        if kind == "m":
            a = _axis_angle(i, n, mode)
            tx, ty = -math.sin(a) * 6, math.cos(a) * 6
            parts.append(f'<line class="radar-tick" x1="{x - tx:.1f}" y1="{y - ty:.1f}" x2="{x + tx:.1f}" y2="{y + ty:.1f}"/>')
    for i, (key, _label, kind, _w2, _s) in enumerate(axes):
        parts.append(_axis_label_svg(i, n, key, kind, mode, ids))
    parts.append('<g class="radar-tools">')
    for tool, var in tools:
        parts.append(_tool_group_svg(device, tool, var, mode, tool in off))
    parts.append("</g></svg>")
    return "".join(parts)


def _tool_vertices(device, tool, mode):
    """[(axis index, key, x, y, qual)] of a tool's present vertices."""
    out = []
    for i, (key, _l, kind, _w, _s) in enumerate(_axes_of(mode)):
        e = device["axes"][key]["tools"].get(tool)
        if e is not None:
            out.append((i, key, *radar_xy(i, e["r"], mode), kind == "q" or bool(e.get("hollow"))))
    return out


def _tool_group_svg(device, tool, var, mode, off=False):
    verts = _tool_vertices(device, tool, mode)
    pts = " ".join(f"{x},{y}" for _i, _k, x, y, _q in verts)
    out = [f'<g class="radar-tool{" is-off" if off else ""}" data-tool="{html.escape(tool, quote=True)}" style="--c:var({var})">']
    if len(verts) >= 2:
        out.append(f'<polygon class="radar-area" points="{pts}"/>')
    for _i, key, x, y, qual in verts:
        out.append(f'<circle class="radar-vertex{" q" if qual else ""}" data-axis="{key}" '
                   f'cx="{x}" cy="{y}" r="{5 if qual else 4}" tabindex="-1"/>')
    out.append("</g>")
    return "".join(out)


def _radar_aria(device, tools, mode):
    parts = []
    for tool, _v in tools:
        scores = []
        for key, label, _k, _w, _s in _axes_of(mode):
            e = device["axes"][key]["tools"].get(tool)
            scores.append(f"{label} {_fmt_score(e['score']) if e else 'no reading'}")
        parts.append(f"{tool}: " + ", ".join(scores))
    return (f"Where each tool shines on {device['name']}, score 1 is the best tool on the axis. "
            + "; ".join(parts) + ".")


def _table_cell(e, kind):
    if not e:
        return "<td>–</td>"
    if kind == "q":
        return "<td>" + html.escape(str(e["value"])) + "</td>"
    return "<td>" + html.escape(f"{e['value']} ({e['ratio']})") + "</td>"


def _radar_table(device, all_tools, mode):
    """The data behind a radar. The landing table lists each major (the mean the radar draws) with its
    minors under it, so the mean can be checked by hand."""
    cols = "".join(f"<th scope=\"col\">{html.escape(t)}</th>" for t, _v in all_tools)
    rows = []
    for key, label, kind, _w, _s in _axes_of(mode):
        cells = [_table_cell(device["axes"][key]["tools"].get(tool), kind) for tool, _v in all_tools]
        rows.append(f'<tr class="major"><th scope="row">{html.escape(label)}</th>{"".join(cells)}</tr>')
        if mode != "landing":
            continue
        for mk in RADAR_MINORS_OF[key]:
            if len(RADAR_MINORS_OF[key]) == 1:
                break
            mkind = RADAR_ALL_AXES[mk][2]
            cells = [_table_cell(device["minor_axes"][mk]["tools"].get(tool), mkind) for tool, _v in all_tools]
            rows.append(f'<tr class="minor"><th scope="row">{html.escape(RADAR_ALL_AXES[mk][1])}</th>{"".join(cells)}</tr>')
    return ('<table class="radar-table"><thead><tr><th scope="col">Axis</th>' + cols + '</tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _radar_json(pool, side, devices, tools, mode):
    """What the script needs: tool list, axes (with the panel's wording), and
    for each device the vertex positions, ring labels and tooltip texts."""
    w, h, cx, cy, _r = RADAR_GEOM[mode]
    data = {"side": side, "mode": mode, "centre": [cx, cy], "geom": list(RADAR_GEOM[mode]),
            "tools": [{"id": t, "color": v} for t, v in tools],
            "axes": [{"key": k, "label": l, "qual": kind == "q", "what": what, "src": src,
                      "edge": RADAR_AXIS_EXTRA[k]["edge"], "dir": RADAR_AXIS_EXTRA[k]["dir"],
                      "ang": round(_axis_angle(i, len(RADAR_MODE_KEYS[mode]), mode), 5),
                      "bands": ([{"r": round(radar_radius_compile(sec), 4), "t": txt} for sec, txt in RADAR_COMPILE_BANDS]
                                if k == "compile" else []),
                      "major": (RADAR_ALL_AXES[RADAR_MAJOR_OF[k]][1].replace(" (qualitative)", "")
                                if k in RADAR_MAJOR_OF else ""),
                      "minors": [{"key": m, "label": RADAR_ALL_AXES[m][1].replace(" (qualitative)", ""),
                                  "qual": RADAR_ALL_AXES[m][2] == "q"} for m in RADAR_MINORS_OF.get(k, ())]
                                if mode == "landing" else []}
                     for i, (k, l, kind, what, src) in enumerate(_axes_of(mode))],
            "devices": {}}
    for slug, dev in devices:
        pts, tips = {}, {}
        for tool, _v in tools:
            pts[tool] = {i: [x, y] for i, _k, x, y, _q in _tool_vertices(dev, tool, mode)}
            tips[tool] = {key: {"v": pool.track(e["value"]), "r": pool.track(e["ratio"]),
                                "a": pool.track(e["arm"]), "d": pool.track(e["detail"])}
                          for key, ax in dev["axes"].items() for t, e in ax["tools"].items() if t == tool}
        # landing: each tool's minors under each major, [value, ratio to best, arm, radius]; a minor the
        # tool has no reading on is absent
        mn = ({tool: {major: {mk: [pool.track(e["value"]), pool.track(e["ratio"]) if RADAR_ALL_AXES[mk][2] == "m" else "",
                                   pool.track(e["arm"]) if RADAR_ALL_AXES[mk][2] == "m" else "", round(e["r"], 4)]
                               for mk, e in ((mk, dev["minor_axes"][mk]["tools"].get(tool)) for mk in minors) if e}
                          for major, minors in RADAR_MINORS_OF.items()} for tool, _v in tools}
              if mode == "landing" else {})
        data["devices"][slug] = {"name": dev["name"], "card": pool.track(dev["card"]), "link": dev["link"],
                                 "pts": pts, "tips": tips, "mn": mn,
                                 "hol": {t: [i for i, _k, _x, _y, q in _tool_vertices(dev, t, mode)
                                             if q and not _axes_of(mode)[i][2] == "q"] for t, _c in tools},
                                 "mdesc": ({k: pool.track(ax["desc"]) for k, ax in dev["minor_axes"].items()} if mode == "landing" else {}),
                                 "mrl": ({k: pool.track(ax["rl"]) for k, ax in dev["minor_axes"].items()} if mode == "landing" else {}),
                                 "desc": {k: pool.track(ax["desc"]) for k, ax in dev["axes"].items()},
                                 "rl": {k: pool.track(ax["rl"]) for k, ax in dev["axes"].items()},
                                 "aria": _radar_aria(dev, tools, mode)}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def _axis_list(mode, ids=""):
    """The numbered axis list shown instead of the in-chart names on a narrow
    column (the names would be too small to read there); each item opens the
    same explanation as the axis name."""
    items = []
    for i, (key, label, kind, _what, _src) in enumerate(_axes_of(mode)):
        d = RADAR_AXIS_EXTRA[key]["dir"]
        note = f' <span class="d">{d}</span>' if d else ""
        items.append(f'<li tabindex="0" data-axis="{key}" value="{i + 1}"><span class="n">{i + 1}</span>'
                     f'<svg class="ic radar-icon" aria-hidden="true" width="20" height="20"><use href="#{_icon_id(ids, key)}"/></svg> '
                     f'{html.escape(label)}{note}</li>')
    return '<ol class="radar-axlist" aria-label="Axes">' + "".join(items) + "</ol>"


def _axis_defs(mode, qualitative):
    """A visible definition list under the chart: every axis of the mode, its name and what it measures,
    as text a reader can find without hovering (the hover panel adds the numbers)."""
    items = []
    for key, label, kind, what, _src in _axes_of(mode):
        text = what or (qualitative["axes"].get(key) or {}).get("rubric", "")
        if text:
            items.append(f"<dt>{html.escape(label)}</dt><dd>{html.escape(text)}</dd>")
    return ('<dl class="radar-defs" aria-label="What each axis measures">' + "".join(items) + "</dl>") if items else ""


def _major_line(minor_keys, kind):
    """"Minors: A, B and C; measured." -- the tail of a major's line in the disclosure."""
    names = [RADAR_ALL_AXES[k][1].replace(" (qualitative)", "") for k in minor_keys]
    if len(names) == 1:
        tail = "A single axis, so nothing is averaged"
    else:
        tail = ", ".join(names[:-1]) + " and " + names[-1]
    return f"{tail}; {'measured' if kind == 'm' else 'qualitative'}."


def build_radar(pool, side, devices, qualitative, mode="landing"):
    """The radar of one side as one HTML block (a ``div.radar``): legend
    buttons, the SVG for the default (first) device, a data table per device
    and the JSON the script morphs between. The detailed mode adds every tool
    to the legend and the explanatory side panel. ``devices`` = [(slug,
    device)] in tab order. Returns '' when there is nothing to draw."""
    if not devices:
        return ""
    all_tools = RADAR_TOOLS[side] + RADAR_TABLE_ONLY[side]
    tools = all_tools if mode == "detailed" else RADAR_TOOLS[side]
    first = devices[0][1]
    out = [f'<div class="radar{" radar-detailed" if mode == "detailed" else ""}" data-side="{side}" data-mode="{mode}">']
    ids = f"{side}-{mode}"
    out.append(_icon_symbols(ids, mode))
    out.append('<div class="radar-legend" role="group" aria-label="Tools">')
    for tool, var in tools:
        out.append(f'<button type="button" class="radar-leg" data-tool="{html.escape(tool, quote=True)}" '
                   f'aria-pressed="{"false" if tool in RADAR_DEFAULT_OFF[side] else "true"}" style="--c:var({var})">'
                   f'<span class="chip"></span>{html.escape(tool)}</button>')
    out.append("</div>")
    out.append('<div class="radar-body"><div class="radar-stage">')
    out.append(radar_static_svg(first, tools, pool.track(_radar_aria(first, tools, mode)), mode, RADAR_DEFAULT_OFF[side], ids))
    out.append('<div class="radar-tip" role="tooltip" hidden></div></div>')
    if mode == "detailed":
        out.append('<aside class="radar-panel" aria-live="polite"><p class="radar-panel-hint">Hover or focus an axis '
                   "name (or a marker) to see what it measures, where its number comes from, and every tool's "
                   "value on it.</p></aside>")
    out.append("</div>")
    out.append(_axis_list(mode, ids))
    out.append(_axis_defs(mode, qualitative))
    for k, (slug, dev) in enumerate(devices):
        hidden = "" if k == 0 else " hidden"
        out.append(f'<div class="radar-dev" data-slug="{html.escape(slug, quote=True)}"{hidden}>')
        out.append(f'<p class="axis-note radar-caption">Radar for {pool.track(html.escape(dev["card"]))}. {RADAR_HOVER_HINT}</p>')
        out.append('<details class="radar-data"><summary>Show the data behind the radar</summary>'
                   + pool.track(_radar_table(dev, all_tools, mode)) + "</details></div>")
    note = RADAR_DETAILED_NOTE if mode == "detailed" else RADAR_NOTE
    out.append(f'<p class="axis-note radar-note radar-note-lead">{note}</p>')
    out.append(f'<p class="axis-note radar-note radar-caption-control">{RADAR_CONTROL_CAPTION}</p>')
    majors = "".join(f"<li><strong>{html.escape(label.replace(' (qualitative)', ''))}</strong>: "
                     f"{html.escape(_major_line(minor_keys, kind))}</li>"
                     for _k, label, kind, _what, _how, minor_keys in RADAR_MAJORS)
    anchors = "".join(f"<li><strong>{html.escape(qualitative['axes'][k]['label'])}</strong>: "
                      f"{html.escape(qualitative['axes'][k].get('anchor', ''))}</li>"
                      for k in RADAR_MODE_KEYS["detailed"] if k in qualitative["axes"]) if mode == "detailed" else ""
    out.append('<details class="radar-data radar-howto"><summary>How to read this radar</summary>'
               f'<p class="axis-note radar-note">{RADAR_MAJOR_RULE}</p><ul class="radar-howto-list radar-howto-majors">{majors}</ul>'
               f'<p class="axis-note radar-note">{RADAR_SCALE_RULE}</p>'
               f'<p class="axis-note radar-note">{RADAR_QUAL_RULE}</p>'
               + (f'<ul class="radar-howto-list radar-howto-anchors">{anchors}</ul>' if anchors else "") +
               f'<p class="axis-note radar-note"><a href="{EAGLE_PERF_PAGE}">Every number, in the full tables</a>.</p>'
               '</details>')
    out.append(f'<script type="application/json" class="radar-json">{_radar_json(pool, side, devices, tools, mode)}</script>')
    out.append("</div>")
    return "\n".join(out)


#: The capability map's source table: tool x block x device -> covered or not, with a source and a note per covered cell.
CAPABILITIES = pathlib.Path("_data") / "capabilities.json"
#: The tools the map offers, in its chip order.
CAPMAP_TOOLS = (("raptor", "--tool-raptor"), ("NVIDIA Warp", "--tool-warp"), ("JAX", "--tool-jax"), ("PyTorch", "--tool-pytorch"),
                ("CuPy", "--tool-cupy"), ("Numba", "--tool-numba"), ("NumPy", "--tool-numpy"))
CAPMAP_CAPTION = ("What each tool has a documented, first-class way to do, on CPU and on GPU; speed is in the bars and the radar.")
CAPMAP_NOTE = ("An icon lights up only when the tool's own documentation shows a designed feature or API for it; a workaround "
               "(masking every lane, raw CUDA strings, running the slowest sample to the end) does not count. Every covered cell "
               "links to its source. The tools are complementary; overlap is not a ranking.")
ROSETTE_NOTE = ("Every radar major fanned open at once, in the radar's order, plus the batches that thin out. A tool's band encloses the "
                "features it covers in a sector: within 2\u00d7 of the best tool on this device (measured, upright) or 4 of 5 in the rubric "
                "(judgement, italic); the arcs on each feature say which tools cover it. Same rule for every tool; overlap is not a ranking.")


def _feat_entry(pool, e):
    return {"v": pool.track(str(e["value"])), "r": pool.track(str(e["ratio"])), "a": e.get("arm", ""), "x": e.get("x"), "pts": e.get("pts")}


def feature_table(pool, dev, divergence):
    """{feature: {tool: entry}} of one radar device for the coverage visuals: the sixteen radar minors plus the two
    divergence features, readings as the radar shows them (value, ratio or reason) and the numbers the coverage rule reads
    (``x`` = ratio to the best, ``pts`` = rubric score)."""
    table = {k: {t: _feat_entry(pool, e) for t, e in ax["tools"].items()} for k, ax in dev["minor_axes"].items()}
    for k, ax in divergence.items():
        table[k] = {t: _feat_entry(pool, e) for t, e in ax["tools"].items()}
    return table


def visual_devices(pool, side, entries, rk78_entries, qualitative):
    """[(slug, name, card line, feature table, date stamp)] for the side's devices in tab order."""
    cards = dict(entries)
    out = []
    for slug, dev in radar_devices(side, entries, rk78_entries, qualitative, "landing"):
        stamp = re.search(r"card of \d{4}-\d{2}-\d{2}", dev["card"])
        out.append((slug, dev["name"], pool.track(dev["card"]), feature_table(pool, dev, divergence_features(pool, side, cards[slug])),
                    stamp.group(0) if stamp else ""))
    return out


def load_capabilities(pool, path=None):
    """The capability map's table (`CAPABILITIES`), recorded in SOURCES.json by md5."""
    p = pool.site_source(CAPABILITIES) if path is None else pathlib.Path(path)
    return visuals.Capabilities(json.loads(p.read_text()))


def build_capmap(pool, sides=("gpu", "cpu")):
    """{side: html block}: the capability map, the same on every device; one copy per hardware panel of the landing
    page (between the bars and the radar), with its ids namespaced by the side."""
    caps = load_capabilities(pool)
    return {side: visuals_markup.capmap_block(side, caps, CAPMAP_TOOLS, CAPMAP_NOTE, CAPMAP_CAPTION) for side in sides}


def build_rosettes(pool, gpu_entries, cpu_entries, rk78_gpu_entries, rk78_cpu_entries, qualitative):
    """{side: html block}: the rosette of each side (all devices), the detailed view of where_raptor_fits."""
    out = {}
    for side, entries, rk in (("gpu", gpu_entries, rk78_gpu_entries), ("cpu", cpu_entries, rk78_cpu_entries)):
        devs = visual_devices(pool, side, entries, rk, qualitative)
        out[side] = visuals_markup.rosette_block(side, RADAR_TOOLS[side], devs, ROSETTE_NOTE) if devs else ""
    return out


def build_radar_page(pool, name, html_block):
    """``_generated/<name>.md``: a radar block as a raw HTML fence."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    if not html_block:
        return w.text(), False
    w.lines.append("```{raw} html")
    w.lines.extend(html_block.split("\n"))
    w.lines.append("```")
    return w.text(), True


def build_radars(pool, gpu_entries, cpu_entries, rk78_gpu_entries, rk78_cpu_entries, qualitative, mode="landing"):
    """{side: html block} for both sides. The axes and their order are the fixed major structure
    (`RADAR_MODE_KEYS`): no search over the data places them."""
    devs = {side: radar_devices(side, entries, rk, qualitative, mode)
            for side, entries, rk in (("gpu", gpu_entries, rk78_gpu_entries), ("cpu", cpu_entries, rk78_cpu_entries))}
    entries_of = {"gpu": gpu_entries, "cpu": cpu_entries}
    blocks = {}
    for side, d in devs.items():
        pool.uneven_eff[side] = eff_sources(pool, side, entries_of[side])
        blocks[side] = build_radar(pool, side, d, qualitative, mode)
    return blocks


def build_detailed_radar(pool, blocks, rosettes=None):
    """``_generated/radar_detailed.md``: the detailed radar of both sides under
    the same hardware pill and device chips as the landing's switch (the URL
    hash is shared), for where_raptor_fits.md."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    sides = [s for s in ("gpu", "cpu") if blocks.get(s)]
    if not sides:
        return w.text(), False
    names = {"gpu": ("On a GPU", "GPU"), "cpu": ("On a CPU", "CPU")}
    lines = ['<div class="perf-switch perf-detailed">']
    for i, side in enumerate(sides):
        lines.append(f'<input type="radio" name="perf-hw" id="perf-hw-{side}" data-side="{side}"{" checked" if i == 0 else ""}>')
    lines.append('<div class="perf-seg" role="radiogroup" aria-label="Hardware">')
    lines += [f'<label for="perf-hw-{side}">{names[side][0]}</label>' for side in sides]
    lines.append("</div>")
    for side in sides:
        chips = re.findall(r'<div class="radar-dev" data-slug="([^"]+)"[^>]*>\n<p class="axis-note radar-caption">Radar for '
                           r'([^,<]+),', blocks[side])
        view = ('<div class="view-toggle" role="group" aria-label="Which view">'
                '<button type="button" class="view-opt" data-view="rosette" aria-pressed="true">Rosette</button>'
                '<button type="button" class="view-opt" data-view="radar" aria-pressed="false">Radar</button></div>')
        both = view + '\n<div class="vis-rosette">\n' + (rosettes or {}).get(side, "") + '\n</div>\n<div class="vis-radar">\n' + blocks[side] + "\n</div>"
        lines += _side_html(side, names[side][1] + " model", [(html.escape(name), "") for _s, name in chips],
                            [slug for slug, _n in chips], both)
    lines.append("</div>")
    w.lines.append("```{raw} html")
    w.lines.extend(lines)
    w.lines.append("```")
    return w.text(), True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _host_compiler(card):
    """The host compiler the card was built with, as its own version line (the card's toolchain string
    is "binary||full version line||hash")."""
    raw = (card.get("toolchain") or {}).get("host_compiler") or ""
    parts = raw.split("||")
    return parts[1] if len(parts) > 1 else raw


def build_compatibility(pool, gpu_entries, cpu_entries):
    """``_generated/compatibility.md``: what the cards MEASURED, per device -- compute capability, GPU driver,
    CUDA runtime and driver API, host compiler -- as two tables; the page that includes it states, beside
    them, what the repositories say is shipped and required."""
    w = Writer(pool)
    w.add("<!-- Generated by tools/sync_cards.py; do not edit. -->")
    w.add("")
    gpus = [(c.get("device") or {}, c) for _s, c in gpu_entries if c.get("device")]
    if not gpus:
        return w.text(), False
    gpus.sort(key=lambda dc: float(dc[0].get("compute_capability") or 0))
    w.add("| GPU measured | compute capability | driver | CUDA runtime / driver API | host compiler |")
    w.add("|---|---|---|---|---|")
    for dev, card in gpus:
        rt, api = _kernel_ver(dev.get("cuda_runtime")), _kernel_ver(dev.get("cuda_driver_api"))
        w.add(f"| {dev.get('name')} | {dev.get('compute_capability')} | {dev.get('driver_version') or '–'} | "
              f"{rt or '–'} / {api or '–'} | {_host_compiler(card) or '–'} |")
    w.add("")
    cpus = [c for _s, c in cpu_entries if isinstance(c.get("cpu"), dict)]
    if cpus:
        w.add("| CPU measured | cores (logical) | platform | host compiler |")
        w.add("|---|---|---|---|")
        for card in cpus:
            c = card["cpu"]
            w.add(f"| {c.get('model')} | {c.get('cores')} ({c.get('logical_cpus')}) | {card.get('platform') or '–'} | "
                  f"{_host_compiler(card) or '–'} |")
        w.add("")
    return w.text(), True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("eagle_root", type=pathlib.Path)
    ap.add_argument("--out-dir", type=pathlib.Path, default=SITE_ROOT / "_generated")
    args = ap.parse_args(argv)

    pool = Pool(args.eagle_root)
    all_cards = {key: family_cards(pool, args.eagle_root, reldir, prefix)
                 for key, (reldir, prefix) in FAMILY_DIRS.items()}
    perf_gpu = default_card(all_cards["perf_gpu"], GPU_PREFERENCE)
    perf_cpu = default_card(all_cards["perf_cpu"], CPU_PREFERENCE)
    rk78_gpu = default_card(all_cards["rk78_gpu"], GPU_PREFERENCE)
    rk78_cpu = default_card(all_cards["rk78_cpu"], CPU_PREFERENCE)

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
    compaction_numbers, have_compaction = build_compaction_numbers(pool, perf_gpu)
    mem_rows, _mem_n = will_it_fit_rows(perf_gpu) if perf_gpu else ([], None)
    compare_memory_chart, have_mem_chart = build_compare_memory_chart(pool, perf_gpu, mem_rows)
    landing_honest, have_landing_honest = build_landing_honest(pool, perf_gpu)
    compatibility, have_compat = build_compatibility(pool, all_cards["perf_gpu"], all_cards["perf_cpu"])
    qualitative = load_qualitative(pool)
    radars = build_radars(pool, all_cards["perf_gpu"], all_cards["perf_cpu"],
                          all_cards["rk78_gpu"], all_cards["rk78_cpu"], qualitative)
    detailed = build_radars(pool, all_cards["perf_gpu"], all_cards["perf_cpu"],
                            all_cards["rk78_gpu"], all_cards["rk78_cpu"], qualitative, "detailed")
    capmap = build_capmap(pool)
    rosettes = build_rosettes(pool, all_cards["perf_gpu"], all_cards["perf_cpu"],
                              all_cards["rk78_gpu"], all_cards["rk78_cpu"], qualitative)
    radar_detailed, have_detailed = build_detailed_radar(pool, detailed, rosettes)
    # landing: under the bars of each side, the capability map (the same on both), then the radar
    landing = {side: (capmap[side] + "\n" + radars[side]) if radars.get(side) else "" for side in radars}
    perf_switch, have_switch = build_perf_switch(pool, all_cards["perf_gpu"], all_cards["perf_cpu"], landing)
    radar_pages = {side: build_radar_page(pool, f"radar_{side}", block) for side, block in radars.items()}

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
    (args.out_dir / "compaction_numbers.md").write_text(compaction_numbers)
    (args.out_dir / "compare_memory_chart.md").write_text(compare_memory_chart)
    (args.out_dir / "landing_honest.md").write_text(landing_honest)
    (args.out_dir / "perf_switch.md").write_text(perf_switch)
    (args.out_dir / "compatibility.md").write_text(compatibility)
    for side, (text, _ok) in radar_pages.items():
        (args.out_dir / f"radar_{side}.md").write_text(text)
    (args.out_dir / "radar_detailed.md").write_text(radar_detailed)

    (args.out_dir / "SOURCES.json").write_text(json.dumps(pool.as_json(), indent=2) + "\n")

    print(f"wrote {args.out_dir} (glance={have_glance}, "
          f"same_task full/short={have_full}/{have_short}, "
          f"hero_strip={have_hero}, honest_box={have_honest}, why_raptor={have_why}, "
          f"lead={have_lead}, compaction={have_compaction}, mem_chart={have_mem_chart}, "
          f"landing_honest={have_landing_honest}, compat={have_compat}, "
          f"radar={'/'.join(str(ok) for _t, ok in radar_pages.values())}/{have_detailed}, "
          f"grid={have_grid}, compare={have_compare}, "
          f"sources={len(pool.sources)}, numbers={len(pool.numbers)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
