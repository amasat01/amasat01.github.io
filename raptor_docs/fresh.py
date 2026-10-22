# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Freshness of a repo's generated docs content, from the ``fresh`` list in its ``docs/raptor_docs.toml``.

    python -m raptor_docs.fresh --check [--site DIR]    # never writes
    python -m raptor_docs.fresh --write [--site DIR]    # re-mint: every generator in write mode

Each entry is a command run from the repo root (``python`` is this interpreter); ``--check`` appends ``--check`` to it, and the
generator exits 0 fresh, 1 stale, 3 a card the docs cite is missing, 4 a tool or companion checkout missing. The site checkout
is passed to the generators as ``$RAPTOR_SITE`` (default ``site``). Exit status: 0, else 4, 3 or 1 (worst first). A copy of a
file this package now ships (``SHADOWS``) is stale by itself: ``--check`` names it and exits 1.
"""
import argparse
import importlib.util
import os
import pathlib
import shlex
import subprocess
import sys

from raptor_docs import config

#: repo-relative globs of files that moved into this package; a repo that still carries one has a second copy that can drift
SHADOWS = ("docs/_tools/nb_*.py", "docs/tools/nb_*.py", "docs/_scripts/nb_*.py", "docs/_static/raptor-tokens.css",
           "docs/_static/raptor-theme.css", "docs/_static/raptor-reveal.css", "docs/_static/fonts", "docs/_static/family_visuals",
           "tools/docs_fresh.sh")
MESSAGES = {"crash": "generator crashed (rc {rc}): {line}",
            1: "out of date: regenerate with: python -m raptor_docs.fresh --write, then commit the result",
            3: "a card the docs cite is missing ({line}): land the card or drop the claim, regeneration will not help",
            4: "generator or companion missing: {line}: check that the paired companion branch has the tool"}


def shadows(root):
    return [p.relative_to(root).as_posix() for pattern in SHADOWS for p in sorted(root.glob(pattern))]


def _missing_tool(argv, root):
    """The first thing the command needs that is not there (a script path, or a ``-m`` module), else None."""
    if argv[1:2] == ["-m"]:
        return None if importlib.util.find_spec(argv[2].split(".")[0]) else argv[2]
    return next((a for a in argv[1:2] if not (root / a).is_file()), None)


def run(root, gens, mode, env):
    """[(command, exit code)] of every generator; the code is 1 for a crash too."""
    results = []
    for gen in gens:
        argv = [sys.executable if t == "python" else t for t in shlex.split(gen)]
        missing = _missing_tool(argv, root)
        if missing:
            print(f"{gen}: {missing} not found", file=sys.stderr)
            results.append((gen, 4))
            continue
        res = subprocess.run(argv + (["--check"] if mode == "check" else []), cwd=root, env=env, capture_output=True, text=True)
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        rc = res.returncode
        crash = "Traceback" in res.stderr or rc not in (0, 1, 3, 4)  # an uncaught exception also exits 1
        results.append((gen, 1 if crash else rc))
        if rc:
            line = (res.stderr.strip() or res.stdout.strip() or "").splitlines()[-1:] or [""]
            print(f"::error::{gen}: " + MESSAGES["crash" if crash else rc].format(line=line[0], rc=rc))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="site", help="the site checkout the generators read (default: site)")
    ap.add_argument("--root", default=None, help="the repo root (default: found from the working directory)")
    args = ap.parse_args(argv)
    if args.check == args.write:
        ap.error("give exactly one of --check, --write")
    cfg = config(args.root)
    root = cfg["root"]
    codes = []
    if args.check:
        for rel in shadows(root):
            print(f"::error::{rel}: a second copy of a file raptor_docs ships; delete it")
            codes.append(1)
    env = {**os.environ, "RAPTOR_SITE": str(pathlib.Path(args.site).resolve())}
    codes += [c for _g, c in run(root, cfg["fresh"], "check" if args.check else "write", env)]
    return next((c for c in (4, 3, 1) if c in codes), 1 if any(codes) else 0)


if __name__ == "__main__":
    sys.exit(main())
