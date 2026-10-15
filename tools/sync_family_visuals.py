# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Build the family-visuals bundle from the landing site's generated assets, and check it.

The bundle is the self-contained set of files a docs site vendors to draw the family's visuals: scripts, one stylesheet,
the icon sprite and the HTML fragments (each with the data tables behind its charts). Each docs repo is a *profile*: it
gets the files and fragments it uses. The bundle is written to ``<repo>/docs/_static/family_visuals/`` together with
``LOCK.json`` (the md5 of every bundle file, of every input, of the cards the site generated from and of the generator).
Nothing is fetched: every input is a file under the site root.

    python sync_family_visuals.py [--site-root S] [--eagle-root E] --target eagle=REPO [--target hawk=REPO ...]
    python sync_family_visuals.py --check [...]       exit 1 on any difference, stale card or stale generator

``--check`` with no ``--target`` builds every profile in memory and checks the transfer budget."""
import argparse
import gzip
import hashlib
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BUNDLE_DIR = "family_visuals"

# ============================================================================ INPUTS: the ONE list to edit
#: Files a profile ships: (bundle path, site source path, transform). "copy" = bytes as they are; "css" = the stylesheet
#: assembled by build_css() from the site's custom.css; "icons" = the icon registry's symbols as one SVG sprite.
FILES = [
    ("perf-state.js", "_static/js/perf-state.js", "copy"),
    ("radar.js", "_static/js/radar.js", "copy"),
    ("visuals.js", "_static/js/visuals.js", "copy"),
    ("visuals.css", "_static/custom.css", "css"),
    ("icons.svg", "tools/radar_icons.py", "icons"),
]
#: The site pages the fragments are cut from (one row each): the landing page's device switch, with the capability map
#: and the landing radar of every device; and the detailed page's radar.
PAGES = {"switch": "_generated/perf_switch.md", "detailed": "_generated/radar_detailed.md"}
#: Fragment kinds. map = the capability map alone (it is the same on every device, so it has no switch);
#:   map_radar = the map, then the device switch with the landing radar of each device;
#:   map_detailed = the map, then the device switch with the detailed radar of each device.
#: Profiles: the docs repo -> {fragment file: kind} and the bundle files it loads.
PROFILES = {
    "eagle": {"fragments": {"map.html": "map", "performance.html": "map_detailed"},
              "files": ["perf-state.js", "radar.js", "visuals.js", "visuals.css", "icons.svg"]},
    "hawk": {"fragments": {"map_radar.html": "map_radar"},
             "files": ["perf-state.js", "radar.js", "visuals.js", "visuals.css", "icons.svg"]},
    "raptor": {"fragments": {"map.html": "map"},
               "files": ["perf-state.js", "visuals.js", "visuals.css", "icons.svg"]},
}
#: The generator's own inputs, hashed into LOCK.json (site-relative; absent ones are skipped).
GENERATOR_FILES = ["tools/sync_cards.py", "tools/visuals.py", "tools/visuals_markup.py", "tools/radar_icons.py",
                   "tools/palette.py"]
SELF_NAME = "sync_family_visuals.py"
#: The site's record of the cards it generated from (paths relative to the eagle checkout).
SOURCES_JSON = "_generated/SOURCES.json"
#: Transfer budget per docs page: the shared scripts and stylesheet plus the page's largest fragment, gzipped (what a
#: reader downloads from a static host). The whole bundle on disk is larger because a repo's pages each carry their own fragment.
BUDGET_GZIP = 300_000
# ============================================================================

CSS = "_static/custom.css"
#: Stylesheet slices: (start marker, end marker or None) of custom.css. Tokens are scoped to the unit; the switch and bars
#: rules lose their id-based lines (the generator writes id-free ones); the radar/map block runs to the end.
CSS_TOKENS = ('/* ---- The tool palette', "/* ---- Typography")
CSS_SLICES = [('/* "How it compares": plain HTML bar charts', '/* "Four libraries"'),
              ('/* "How it compares": hover and focus on a runtime bar', '/* The landing radar (radar_gpu.md'),
              ('/* The landing radar (radar_gpu.md', None)]
MAX_CHIPS = 12


def md5(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def self_path(site_root):
    for cand in (site_root / "tools" / SELF_NAME, pathlib.Path(__file__).resolve()):
        if cand.is_file():
            return cand
    raise SystemExit(f"cannot find {SELF_NAME}")


def _minify_css(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r" ?([{};]) ?", r"\1", text).strip()


def build_css(site):
    css = (site / CSS).read_text()
    # the site's palette, scoped to the unit so it never leaks into (or is overridden by) a docs theme
    i0 = css.index('/* ---- The tool palette')
    tokens_a = css[css.index(':root, html[data-theme="light"] {'):css.index("/* ---- The tool palette")]
    tokens_b = css[i0:css.index(CSS_TOKENS[1])]
    toks = tokens_a + tokens_b
    toks = toks.replace(':root, html[data-theme="light"] {', '.perf-switch, html[data-theme="light"] .perf-switch {')
    toks = toks.replace('html[data-theme="dark"] {', 'html[data-theme="dark"] .perf-switch {')
    parts = [toks, ".perf-switch { --w-strong: 620; }"]
    for a, b in CSS_SLICES:
        i = css.index(a)
        j = css.index(b) if b else len(css)
        seg = css[i:j]
        seg = "\n".join(ln for ln in seg.splitlines() if not re.match(r"\s*(#perf-hw-|\.perf-side > input:nth-of-type)", ln))
        parts.append(seg)
    # the switch rules, id-free: a unit carries more than one switch-less panel and any number of chips
    gen = ["/* The unit's own switch (generated): hardware pill and device chips, by position, not by id. */"]
    for side, n in (("gpu", 1), ("cpu", 2)):
        gen.append(f'.perf-switch > input[data-side="{side}"]:checked ~ .perf-side-{side} {{ display: block; }}')
        gen.append(f'.perf-switch > input[data-side="{side}"]:checked ~ .perf-seg label:nth-of-type({n}) {{ background: var(--raptor); color: var(--on-raptor); }}')
        gen.append(f'.perf-switch > input[data-side="{side}"]:focus-visible ~ .perf-seg label:nth-of-type({n}) {{ outline: 2px solid var(--raptor); outline-offset: 2px; }}')
    for k in range(1, MAX_CHIPS + 1):
        gen.append(f".perf-side > input:nth-of-type({k}):checked ~ .perf-dev:nth-of-type({k}) {{ display: block; }}")
        gen.append(f".perf-side > input:nth-of-type({k}):checked ~ .perf-chips label:nth-of-type({k}) {{ background: var(--raptor-wash); border-color: var(--raptor-soft); color: var(--rpt-ink); }}")
        gen.append(f".perf-side > input:nth-of-type({k}):focus-visible ~ .perf-chips label:nth-of-type({k}) {{ outline: 2px solid var(--raptor); outline-offset: 2px; }}")
    # a docs theme may size a closed or open <details> to its content: keep the data tables inside the column
    gen.append(".perf-switch { max-width: 100%; min-width: 0; } .perf-switch details.radar-data { display: block; max-width: 100%; overflow-x: auto; }")
    parts.append("\n".join(gen))
    return (_minify_css("\n".join(parts)) + "\n").encode()


def _icons(site_root):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(site_root / "tools"))
    try:
        import radar_icons
    finally:
        sys.path.pop(0)
    syms = "".join(f'<symbol id="rico-{k}" viewBox="0 0 24 24">{v}</symbol>' for k, v in sorted(radar_icons.ICONS.items()))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" '
            f'stroke-width="{radar_icons.ICON_STROKE}" stroke-linecap="round" stroke-linejoin="round">'
            f"{syms}</svg>\n").encode()


# ---------------------------------------------------------------- fragments
def _raw_html(text):
    m = re.search(r"```\{raw\} html\n(.*?)\n```\s*$", text, re.S)
    if not m:
        raise SystemExit("page is not a single {raw} html block")
    return m.group(1)


def _split_sides(html):
    """{side: segment} of a switch page: the head is everything before the first side."""
    ig, ic = html.index('<div class="perf-side perf-side-gpu">'), html.index('<div class="perf-side perf-side-cpu">')
    return html[:ig], {"gpu": html[ig:ic], "cpu": html[ic:]}


def _side_open(seg):
    return seg[:seg.index('<section class="perf-dev">')]


def _block(seg, start_re):
    """A visual block (worlds / radar): from its opening tag to its closing '</script>\\n</div>' (the JSON ends each block)."""
    m = re.search(start_re, seg)
    if not m:
        raise SystemExit(f"block {start_re} not found")
    return seg[m.start():seg.index("</script>\n</div>", m.start()) + len("</script>\n</div>")] + "\n"


def _unit(kind, pages):
    sw = _raw_html(pages["switch"])
    head, sides = _split_sides(sw)
    head = head.replace('<span id="on-your-cpu"></span>\n', "")
    capmap = _block(sides["gpu"], r'<div class="capmap" data-side="gpu"')
    if kind == "map":
        html = f'<div class="perf-switch" data-fv="{kind}">\n' + capmap + "</div>"
        html = re.sub(r"<details\b(?![^>]*\bopen\b)", "<details open data-nojs", html)
        return html.encode() + b"\n"
    cls = "perf-switch perf-detailed" if kind == "map_detailed" else "perf-switch"
    # the map once, first: it is the same on every device, and the switch under it picks the radar's device
    head = head.replace('<div class="perf-switch">', f'<div class="{cls}" data-fv="{kind}"' + ">\n" + capmap.rstrip("\n"), 1)
    det_sides = _split_sides(_raw_html(pages["detailed"]))[1] if kind == "map_detailed" else None
    out = [head]
    for side, seg in sides.items():
        opening = _side_open(seg)
        out.append(opening)
        secs = re.findall(r'<section class="perf-dev">.*?</section>\n', seg, re.S)
        out.append('<section class="perf-dev">\n</section>\n' * len(secs))
        if kind == "map_radar":
            out.append(_block(seg, rf'<div class="radar" data-side="{side}" data-mode="landing">'))
        elif kind == "map_detailed":
            d = det_sides[side]
            i = d.index('<div class="radar radar-detailed"')
            j = d.rindex("</script>\n</div>\n</div>") + len("</script>\n</div>\n</div>") + 1
            out.append(d[i:j])
        out.append("</div>\n")
    out.append("</div>")
    html = "".join(out)
    # ids unique per unit (a page's own switch keeps its ids); names stay: the scripts read them
    html = re.sub(r'\b(id|for)="perf-', rf'\1="fv-{kind}-', html)
    # readers without script get the data tables open; family_visuals.js closes them again when script runs
    html = re.sub(r"<details\b(?![^>]*\bopen\b)", "<details open data-nojs", html)
    return html.encode() + b"\n"


NOJS = (b'/* Closes the data tables that are open in the page source so that a reader without script sees them. */\n'
        b'document.addEventListener("DOMContentLoaded", function () {\n'
        b'  document.querySelectorAll("details[data-nojs]").forEach(function (d) { d.removeAttribute("open"); });\n'
        b'});\n')


def build(site_root, profile):
    """{bundle path: bytes} of one profile, LOCK.json included."""
    prof = PROFILES[profile]
    files = {}
    for dest, src, how in FILES:
        if dest not in prof["files"]:
            continue
        path = site_root / src
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
        files[dest] = _icons(site_root) if how == "icons" else build_css(site_root) if how == "css" else path.read_bytes()
    pages = {}
    for key, rel in PAGES.items():
        if not (site_root / rel).is_file():
            raise SystemExit(f"missing input: {site_root / rel}")
        pages[key] = (site_root / rel).read_text()
    for name, kind in prof["fragments"].items():
        files["fragments/" + name] = _unit(kind, pages)
    files["family_visuals.js"] = NOJS
    files["assets.json"] = (json.dumps({
        "css": sorted(d for d in files if d.endswith(".css")),
        "js": [d for d in files if d.endswith(".js") and d != "family_visuals.js"] + ["family_visuals.js"],
    }, indent=2) + "\n").encode()
    sources = json.loads((site_root / SOURCES_JSON).read_text())
    cards = {s["path"]: s["md5"] for s in sources["sources"]}
    gen = {name: md5((site_root / name).read_bytes()) for name in GENERATOR_FILES if (site_root / name).is_file()}
    gen[SELF_NAME] = md5(self_path(site_root).read_bytes())
    inputs = {rel: md5((site_root / rel).read_bytes()) for rel in sorted({s for _, s, _ in FILES if (site_root / s).is_file()} | set(PAGES.values()))}
    lock = {"profile": profile, "files": {d: md5(b) for d, b in sorted(files.items())}, "inputs": inputs,
            "cards": dict(sorted(cards.items())), "generator": dict(sorted(gen.items()))}
    files["LOCK.json"] = (json.dumps(lock, indent=2) + "\n").encode()
    return files


def sizes(files):
    """(raw bytes of the bundle, gzipped bytes of the bundle, gzipped bytes of the heaviest page: shared files + largest fragment)."""
    gz = {k: len(gzip.compress(b, 9, mtime=0)) for k, b in files.items()}
    shared = sum(v for k, v in gz.items() if not k.startswith("fragments/"))
    page = shared + max((v for k, v in gz.items() if k.startswith("fragments/")), default=0)
    return sum(len(b) for b in files.values()), sum(gz.values()), page


def target_dir(repo):
    base = repo / "docs" if (repo / "docs").is_dir() else repo
    return base / "_static" / BUNDLE_DIR


def on_disk(tdir):
    return {p.relative_to(tdir).as_posix(): p.read_bytes() for p in sorted(tdir.rglob("*")) if p.is_file()} if tdir.is_dir() else {}


def _targets(items):
    out = []
    for it in items:
        name, sep, path = it.partition("=")
        if not sep or name not in PROFILES:
            raise SystemExit(f"--target takes <profile>=<repo path>, profile one of {sorted(PROFILES)}: {it!r}")
        out.append((name, pathlib.Path(path).resolve()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--site-root", type=pathlib.Path, default=pathlib.Path(os.environ.get("RAPTOR_SITE_ROOT", HERE.parent)))
    ap.add_argument("--eagle-root", type=pathlib.Path, default=os.environ.get("RAPTOR_EAGLE_ROOT"))
    ap.add_argument("--target", action="append", default=[], metavar="PROFILE=REPO")
    a = ap.parse_args(argv)
    site = a.site_root.resolve()
    targets = _targets(a.target)
    bad = []
    for profile in PROFILES:
        raw, total, page = sizes(build(site, profile))
        if page > BUDGET_GZIP:
            bad.append(f"profile {profile}: the heaviest page loads {page} bytes gzipped, over the {BUDGET_GZIP} budget")
    if a.check:
        for profile, repo in targets:
            want, have = build(site, profile), on_disk(target_dir(repo))
            for name in sorted(set(want) | set(have)):
                if want.get(name) != have.get(name):
                    bad.append(f"{repo.name}: {name} " + ("missing" if name not in have else "unexpected" if name not in want else "differs"))
        if a.eagle_root:
            for rel, want_md5 in json.loads(build(site, "raptor")["LOCK.json"])["cards"].items():
                card = pathlib.Path(a.eagle_root) / rel
                if not card.is_file() or md5(card.read_bytes()) != want_md5:
                    bad.append(f"card {rel}: stale or missing in {a.eagle_root}")
        if bad:
            print("family visuals are out of date:\n  " + "\n  ".join(bad), file=sys.stderr)
            print(f"regenerate with: python {self_path(site)} --site-root {site} --target <profile>=<repo> ...", file=sys.stderr)
            return 1
        print(f"family visuals up to date ({len(targets)} target(s), {len(PROFILES)} profile(s) within budget)")
        return 0
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    for profile, repo in targets:
        want = build(site, profile)
        tdir = target_dir(repo)
        for name in set(on_disk(tdir)) - set(want):
            (tdir / name).unlink()
        for name, data in want.items():
            p = tdir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        raw, total, page = sizes(want)
        print(f"wrote {profile}: {len(want)} files to {tdir} ({raw} bytes, {total} gzipped, heaviest page {page} gzipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
